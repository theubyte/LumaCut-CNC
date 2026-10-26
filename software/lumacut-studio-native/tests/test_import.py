"""Import (SVG/DXF/Bild), Bildobjekt-Modell und Bild-G-Code."""
from __future__ import annotations

import json
import math
import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM


def _doc():
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    return d


def _png(qapp, w=40, h=20, dpi=254, gradient=True, alpha=False):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format_ARGB32 if alpha else QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255, 0 if alpha else 255))
    for x in range(w):
        for y in range(h):
            v = int(255 * x / max(1, w - 1)) if gradient else 0
            if not alpha or x < w // 2:
                img.setPixelColor(x, y, QColor(v, v, v))
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    return img


def _image_shape(qapp, doc, x=50, y=50, w=20, h=10, rot=0.0, **settings):
    from lumacut_import.image import grayscale_png
    png, pw, ph = grayscale_png(_png(qapp))
    sh = Shape("image", Geometry(x, y, w, h, rot), doc.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    doc.add_shape(sh)
    return sh


# ------------------------------------------------------------- Modell
def test_image_roundtrip_and_version(qapp):
    d = _doc()
    sh = _image_shape(qapp, d, mode="grayscale", line_interval_mm=0.2)
    data = json.loads(json.dumps(d.to_dict()))
    assert data["version"] == Document.VERSION
    d2 = Document.from_dict(data)
    s2 = d2.shapes[0]
    assert s2.kind == "image" and s2.image.png == sh.image.png
    assert s2.image.settings.mode == "grayscale" and s2.image.settings.line_interval_mm == 0.2
    assert s2.image.dpi(20) == pytest.approx(40 / 20 * 25.4)


def test_image_settings_are_clamped():
    st = ImageSettings.from_dict({"mode": "foo", "power": 500, "line_interval_mm": 0,
                                  "unknown": 1, "depth_levels": 1000})
    assert st.mode == "floyd" and st.power == 100 and st.line_interval_mm == 0.03
    assert st.depth_levels == 64


def test_corrupt_image_rejected():
    with pytest.raises(ValueError):
        RasterImage.from_dict({"png": "AAAA", "px": [1, 1]})


def test_image_settings_undo(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.commands import SetImageSettingsCommand
    d = _doc()
    sh = _image_shape(qapp, d)
    stack = QUndoStack()
    old = sh.image.settings
    stack.push(SetImageSettingsCommand(d, sh.id, old, ImageSettings(mode="threshold")))
    assert d.shape(sh.id).image.settings.mode == "threshold"
    stack.undo()
    assert d.shape(sh.id).image.settings == old


# ------------------------------------------------------------- Bild-G-Code
@pytest.mark.parametrize("mode", ["threshold", "floyd", "atkinson", "ordered", "grayscale", "depth3d"])
def test_image_job_is_pi_safe(qapp, mode):
    from lumacut_job.planner import optimized_document_gcode
    d = _doc()
    _image_shape(qapp, d, mode=mode, line_interval_mm=0.5, depth_levels=4)
    d.add_shape(Shape("rect", Geometry(10, 10, 20, 20), d.active_layer_id))
    g = optimized_document_gcode(d)
    pi_check(g)
    lines = g.splitlines()
    assert lines[1:5] == ["G21", "G90", "M5 I", "M3 I"] and lines[-2:] == ["M5 I", "M400"]
    assert g.count("M3 I") == 1 and "G28" not in g
    assert not [l for l in lines if l.startswith("G0") and " S" in l]
    # Bild vor Vektor (gravieren vor schneiden)
    assert g.index("; IMAGE") < g.index("; LAYER")
    if mode == "depth3d":
        assert "; SLICE" in g


def test_rotated_image_stays_inside_bbox(qapp):
    from lumacut_job.images import render_gray
    from lumacut_canvas.workarea import to_machine
    d = _doc()
    sh = _image_shape(qapp, d, rot=30, line_interval_mm=0.25)
    gray, (x, y) = render_gray(sh, 0.25)
    b = sh.geom.bounds()
    assert gray.shape == (round(b.h / 0.25), round(b.w / 0.25))
    assert gray[0, 0] == 255  # Ecke außerhalb des gedrehten Bildes: nicht lasern
    from lumacut_job.planner import optimized_document_gcode
    g = optimized_document_gcode(d)
    pi_check(g)
    xs = [float(v) for v in re.findall(r"G1 X([\d.]+)", g)]
    mx0, mx1 = sorted((to_machine(b.x, b.y)[0], to_machine(b.right, b.bottom)[0]))  # X gespiegelt
    assert min(xs) >= mx0 - 3.001 and max(xs) <= mx1 + 3.001


def test_overscan_clamped_at_work_area_edge(qapp):
    from lumacut_job.planner import optimized_document_gcode
    d = _doc()
    _image_shape(qapp, d, x=0, y=0, w=20, h=10, line_interval_mm=0.5, overscan_mm=10)
    pi_check(optimized_document_gcode(d))


def test_negative_and_hidden_layer(qapp):
    from lumacut_job.planner import optimized_document_gcode
    d = _doc()
    _image_shape(qapp, d, negative=True, line_interval_mm=0.5)
    pi_check(optimized_document_gcode(d))
    for layer in d.layers:
        layer.visible = False
    with pytest.raises(ValueError):
        optimized_document_gcode(d)


def test_vector_only_output_unchanged(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    from lumacut_job.planner import optimize_layers, optimized_document_gcode
    d = _doc()
    d.add_shape(Shape("ellipse", Geometry(10, 10, 20, 20), d.active_layer_id))
    assert optimized_document_gcode(d) == layers_to_gcode(optimize_layers(job_layers(d)))


def test_frame_includes_images(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.estimate import frame_gcode
    from lumacut_job.images import image_outline_layers
    d = _doc()
    _image_shape(qapp, d, x=100, y=100, w=30, h=10)
    assert job_layers(d) == []
    g = frame_gcode(image_outline_layers(d))
    pi_check(g)
    assert "X260.000" in g and "X290.000" in g  # 390 − (100 … 130), Nullpunkt oben rechts


# ------------------------------------------------------------- SVG
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 200 100">
 <g transform="translate(10,0)">
  <rect x="0" y="0" width="20" height="10"/>
  <circle cx="50" cy="50" r="10"/>
  <ellipse cx="100" cy="50" rx="20" ry="10" transform="rotate(30 100 50)"/>
  <polyline points="0,60 10,70 20,60"/>
  <polygon points="0,80 10,90 20,80"/>
  <path d="M 120 10 C 130 0 150 0 160 10 A 10 10 0 0 1 160 30 Z M 170 10 L 180 20"/>
  <text x="1" y="1">Hallo</text>
  <line x1="0" y1="95" x2="50" y2="95"/>
 </g>
</svg>"""


def test_svg_units_transforms_and_kinds(tmp_path):
    from lumacut_import.vector import load_svg
    p = tmp_path / "a.svg"
    p.write_text(SVG)
    vi = load_svg(p)
    closed = [pl for pl in vi.polylines if pl.closed]
    open_ = [pl for pl in vi.polylines if not pl.closed]
    assert len(closed) == 5 and len(open_) == 3
    assert vi.skipped == {"Text": 1}
    rect = vi.polylines[0]
    xs = [x for x, _ in rect.points]
    ys = [y for _, y in rect.points]
    # viewBox 200 → 100 mm: Faktor 0.5, translate(10) → x 5..15 mm
    assert min(xs) == pytest.approx(5) and max(xs) == pytest.approx(15)
    assert max(ys) == pytest.approx(5)
    circle = vi.polylines[1]
    r = [math.dist(p, (30, 25)) for p in circle.points]
    assert min(r) == pytest.approx(5, abs=0.06) and max(r) == pytest.approx(5, abs=0.06)


def test_svg_import_places_group_and_keeps_position(tmp_path, qapp):
    from lumacut_import import import_file
    p = tmp_path / "a.svg"
    p.write_text(SVG)
    res = import_file(p, "L1")
    assert res.scale == 1.0 and len(res.shapes) == 8
    assert len({s.groups for s in res.shapes}) == 1 and res.shapes[0].groups
    kinds = {s.kind for s in res.shapes}
    assert kinds == {"polygon", "path"}
    assert min(s.bounds().x for s in res.shapes) == pytest.approx(5)
    assert "1× Text übersprungen" in res.summary("a.svg")


def test_oversize_svg_is_scaled_into_work_area(tmp_path):
    from lumacut_import import import_file
    p = tmp_path / "big.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1000mm" height="200mm" '
                 'viewBox="0 0 1000 200"><rect x="0" y="0" width="1000" height="200"/>'
                 '<rect x="10" y="10" width="10" height="10"/></svg>')
    res = import_file(p, "L1")
    assert res.scale == pytest.approx(0.36)
    b = [s.bounds() for s in res.shapes]
    assert max(r.right for r in b) <= WORK_WIDTH_MM + 1e-6
    assert max(r.bottom for r in b) <= WORK_HEIGHT_MM + 1e-6
    assert b[1].w == pytest.approx(3.6)
    assert "verkleinert" in res.summary("big.svg")


def test_drop_position_centers_and_clamps(tmp_path):
    from lumacut_import import import_file
    p = tmp_path / "r.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" '
                 'viewBox="0 0 20 10"><rect x="0" y="0" width="20" height="10"/></svg>')
    s = import_file(p, "L1", drop=(100, 100)).shapes[0]
    assert (s.geom.x, s.geom.y) == pytest.approx((90, 95))
    s = import_file(p, "L1", drop=(359, 1)).shapes[0]
    assert s.bounds().right == pytest.approx(WORK_WIDTH_MM) and s.geom.y == pytest.approx(0)


def test_empty_or_bad_files(tmp_path):
    from lumacut_import import import_file
    p = tmp_path / "e.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>x</text></svg>')
    with pytest.raises(ValueError, match="keine"):
        import_file(p, "L1")
    q = tmp_path / "x.cdr"  # .ai ist seit Anforderungen §9.2 unterstützt
    q.write_text("x")
    with pytest.raises(ValueError, match="nicht unterstützt"):
        import_file(q, "L1")
    with pytest.raises(ValueError, match="Keine gültige AI-Datei"):
        import_file(q.rename(tmp_path / "x.ai"), "L1")
    r = tmp_path / "broken.png"
    r.write_bytes(b"nope")
    with pytest.raises(ValueError):
        import_file(r, "L1")


# ------------------------------------------------------------- DXF
def _dxf(tmp_path, insunits=4):
    import ezdxf
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_lwpolyline([(0, 20, 0, 0, 1), (10, 20), (10, 30), (0, 30)], format="xyseb", close=True)
    msp.add_circle((50, 50), 5)
    msp.add_arc((80, 50), 5, 0, 90)
    msp.add_spline([(0, 60), (10, 70), (20, 60), (30, 70)])
    msp.add_ellipse((100, 50), major_axis=(10, 0), ratio=0.5)
    pl = msp.add_polyline2d([(120, 0), (130, 0), (130, 10)], close=True)
    assert pl
    msp.add_text("Hallo")
    blk = doc.blocks.new("B")
    blk.add_line((0, 0), (5, 5))
    msp.add_blockref("B", (200, 0))
    p = tmp_path / "t.dxf"
    doc.saveas(p)
    return p


def test_dxf_entities_and_units(tmp_path):
    from lumacut_import.vector import load_dxf
    vi = load_dxf(_dxf(tmp_path))
    assert vi.skipped == {"TEXT": 1}
    assert len(vi.polylines) == 8  # 7 Objekte + Linie aus dem Block
    closed = sum(pl.closed for pl in vi.polylines)
    assert closed == 4  # lwpolyline, circle, ellipse, polyline2d
    line = vi.polylines[0]
    assert line.points == [(0, WORK_HEIGHT_MM), (10, WORK_HEIGHT_MM)]  # y gespiegelt
    circle = vi.polylines[2]
    assert all(math.dist(p, (50, WORK_HEIGHT_MM - 50)) == pytest.approx(5, abs=0.06)
               for p in circle.points)
    bulge = vi.polylines[1]
    assert len(bulge.points) > 6  # Bogen (bulge) wurde zerlegt
    vi_in = load_dxf(_dxf(tmp_path, insunits=1))  # Zoll
    assert vi_in.polylines[0].points[1][0] == pytest.approx(254)


def test_dxf_import_fits_work_area(tmp_path):
    from lumacut_import import import_file
    res = import_file(_dxf(tmp_path, insunits=1), "L1")  # Zoll → ~5 m breit
    assert res.scale < 1
    for s in res.shapes:
        b = s.bounds()
        assert b.x >= -1e-6 and b.right <= WORK_WIDTH_MM + 1e-6
        assert b.y >= -1e-6 and b.bottom <= WORK_HEIGHT_MM + 1e-6


# ------------------------------------------------------------- Bitmaps
@pytest.mark.parametrize("fmt", ["png", "jpg", "bmp"])
def test_bitmap_import_size_from_dpi(tmp_path, qapp, fmt):
    from lumacut_import import import_file
    p = tmp_path / f"b.{fmt}"
    assert _png(qapp, 100, 50, dpi=254).save(str(p))
    res = import_file(p, "L1")
    s = res.shapes[0]
    assert res.kind == "image" and s.kind == "image"
    if fmt != "jpg" or s.geom.w == pytest.approx(10):  # JPEG speichert DPI nicht immer
        assert (s.geom.w, s.geom.h) == pytest.approx((10, 5))
    assert (s.geom.x, s.geom.y) == (0, 0)
    assert s.image.px_width == 100 and s.image.png.startswith(b"\x89PNG")


def test_bitmap_alpha_becomes_white(tmp_path, qapp):
    import numpy as np
    from lumacut_import.image import load_image
    from lumacut_canvas.image_cache import qimage_for
    p = tmp_path / "a.png"
    _png(qapp, 20, 4, gradient=False, alpha=True).save(str(p))
    img, _, _ = load_image(p)
    q = qimage_for(img.png)
    assert q.pixelColor(2, 1).red() == 0 and q.pixelColor(18, 1).red() == 255


def test_huge_bitmap_is_scaled_into_work_area(tmp_path, qapp):
    from lumacut_import import import_file
    p = tmp_path / "huge.png"
    _png(qapp, 2000, 100, dpi=72, gradient=False).save(str(p))  # 705 mm breit
    s = import_file(p, "L1").shapes[0]
    assert s.geom.w == pytest.approx(WORK_WIDTH_MM)
