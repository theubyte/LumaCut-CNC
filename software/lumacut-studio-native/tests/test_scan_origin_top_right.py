"""Scan Probe bei Nullpunkt oben rechts (Anforderungen 2026-10-26 §2.3).

Bildschirm (Canvas) bleibt oben links; Maschine = (390 − x, 30 + y). Geprüft wird,
dass Platzierung (Rechtecke, Bereiche, Beschriftung) und Bilder (Mosaik,
Höhenkarte) für beide Konventionen zur Maschine passen. ``flipped`` und
``legacy`` ersetzen die Umrechnung im Panel; ``real`` nimmt die aus
``lumacut_canvas.workarea`` (je nach Stand des Canvas-Pakets).
"""
from __future__ import annotations

import numpy as np
import pytest

from scanprobe.detection import DetectedObject
from scanprobe.geometry import Polygon, Rect
from scanprobe.heightmap import MEASURED, HeightMap, HeightMapSet
from scanprobe.stitch import Mosaic

CONVENTIONS = {
    "flipped": (lambda x, y: (390.0 - x, y + 30.0), lambda x, y: (390.0 - x, y - 30.0)),
    "legacy": (lambda x, y: (x + 30.0, y + 30.0), lambda x, y: (x - 30.0, y - 30.0)),
}


@pytest.fixture(params=["real", "flipped", "legacy"])
def conv(request, monkeypatch):
    import scanprobe.panel as P
    if request.param != "real":
        to_m, from_m = CONVENTIONS[request.param]
        monkeypatch.setattr(P, "to_machine", to_m)
        monkeypatch.setattr(P, "from_machine", from_m)
    return P


@pytest.fixture()
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()


@pytest.fixture()
def panel(qapp, editor):
    from scanprobe.panel import ScanPanel
    p = ScanPanel(editor, ask=False)
    yield p
    p.shutdown()


def _maps(rect: Rect) -> HeightMapSet:
    xs = np.arange(rect.xmin, rect.xmax + 0.1, 5.0)
    ys = np.arange(rect.ymin, rect.ymax + 0.1, 5.0)
    hm = HeightMap.empty("a", rect.to_polygon(), xs, ys)
    for j in range(len(ys)):
        for i in range(len(xs)):
            hm.set(i, j, 3.0, MEASURED)
    return HeightMapSet([hm])


def test_point_round_trip_and_flip(conv):
    P = conv
    for mx, my in [(30, 30), (390, 370), (100, 50), (355.5, 222.25)]:
        sx, sy = P.from_machine(mx, my)
        assert 0 <= sx <= 360 and 0 <= sy <= 340
        assert P.to_machine(sx, sy) == pytest.approx((mx, my))
    flip = P.to_machine(0, 0)[0] == pytest.approx(390)
    assert P.image_flip_x() == flip
    # Maschinen-X 100 liegt 70 mm vom Nullpunkt: gespiegelt also rechts (Bildschirm 290)
    assert P.from_machine(100, 50) == pytest.approx((290, 20) if flip else (70, 20))


def test_rects_from_two_corners_are_sorted(conv):
    P = conv
    assert P.work_rect_machine() == Rect(30, 30, 390, 370)
    r = P.machine_rect(10, 20, 50, 80)   # Bildschirm-Ecken
    assert r.xmin < r.xmax and r.ymin < r.ymax
    assert (r.width, r.height) == pytest.approx((40, 60))
    assert r.contains(*P.to_machine(30, 50))


def test_design_bounds_and_roi_in_machine_mm(conv, panel, editor):
    P = conv
    from lumacut_canvas.model import Geometry, Shape
    d = editor.document
    d.add_shape(Shape("rect", Geometry(10, 20, 40, 60), d.active_layer_id))
    (b,) = panel.design_bounds()
    exp = P.machine_rect(10, 20, 50, 80)
    assert (b.xmin, b.ymin, b.xmax, b.ymax) == pytest.approx((exp.xmin, exp.ymin, exp.xmax, exp.ymax))
    # Aufgezogener Bereich auf dem Canvas -> manueller Probe-Bereich an derselben Stelle
    panel._marking = True
    panel._on_roi(100, 100, 50, 30)
    (area,) = panel.manual_areas
    ab = area.polygon.bounds
    want = P.machine_rect(100, 100, 150, 130)
    assert (ab.xmin, ab.ymin, ab.xmax, ab.ymax) == pytest.approx((want.xmin, want.ymin, want.xmax, want.ymax))
    # Overlay des Bereichs liegt wieder auf dem aufgezogenen Bildschirm-Rechteck
    br = panel.overlay.manual_items[0].path().boundingRect()
    assert (br.left(), br.top(), br.right(), br.bottom()) == pytest.approx((100, 100, 150, 130))


def test_object_outline_and_label_on_screen(conv, panel):
    P = conv
    poly = Polygon([(60, 40), (100, 40), (100, 70), (60, 70)])   # Maschinen-mm
    obj = DetectedObject("o1", "rectangle", poly, poly.bounds, (80, 55), 1200, 1.0)
    panel.overlay.set_objects([obj])
    path_item, label = panel.overlay.object_items
    br = path_item.path().boundingRect()
    sx = sorted([P.from_machine(60, 0)[0], P.from_machine(100, 0)[0]])
    assert (br.left(), br.right(), br.top(), br.bottom()) == pytest.approx((sx[0], sx[1], 10, 40))
    # Beschriftung an der linken oberen Bildschirmecke des Werkstücks
    assert (label.pos().x(), label.pos().y()) == pytest.approx((br.left(), br.top()))


def test_mosaic_aligns_with_canvas(conv):
    P = conv
    img = np.zeros((340, 360, 3), np.uint8)          # Maschine X30–390, Y30–370, 1 mm/px
    img[100 - 30:110 - 30, 50 - 30:60 - 30] = 255    # Marke bei Maschine X50–60, Y100–110
    mosaic = Mosaic(img, 1.0, (30.0, 30.0), np.ones(img.shape[:2], bool))
    out = P.mosaic_to_work_image(mosaic, mm_per_px=1.0)
    assert out.shape[:2] == (340, 360)
    sx, sy = P.from_machine(55, 105)                 # Mitte der Marke auf dem Bildschirm
    assert out[int(sy), int(sx)].min() > 200
    mx = 360 - int(sx)                               # gespiegelte Stelle bleibt dunkel
    assert out[int(sy), mx].max() < 50


def test_heatmap_aligns_with_canvas(conv, panel):
    P = conv
    lo_hi = panel.overlay.set_heatmap(_maps(Rect(40, 40, 80, 80)), px_per_mm=2.0)
    assert lo_hi is not None
    item = panel.overlay.heat_item
    assert item.pos().x() == 0 and item.pos().y() == 0
    qimg = item.pixmap().toImage()
    sx, sy = P.from_machine(60, 60)                  # Mitte des Meshes
    assert qimg.pixelColor(int(sx * 2), int(sy * 2)).alpha() > 0
    assert qimg.pixelColor(int((360 - sx) * 2), int(sy * 2)).alpha() == 0


def test_flipped_canvas_export_matches_mesh(panel, editor):
    """Echte Kette: Form auf dem Canvas -> G-Code (Canvas-Umrechnung) und
    Probe-Bereich (Scan-Umrechnung) -> Mesh deckt den Auftrag vollständig ab."""
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job.planner import optimized_document_gcode
    from scanprobe.focus_export import compensate_for_export
    d = editor.document
    d.add_shape(Shape("rect", Geometry(20, 30, 40, 25), d.active_layer_id))
    (b,) = panel.design_bounds()
    maps = _maps(Rect(b.xmin - 1, b.ymin - 1, b.xmax + 1, b.ymax + 1))
    assert maps.map_for(*b.center) is not None
    res = compensate_for_export(optimized_document_gcode(d), maps)
    assert res.ok, res.errors
    assert res.coverage.outside_mm == 0
