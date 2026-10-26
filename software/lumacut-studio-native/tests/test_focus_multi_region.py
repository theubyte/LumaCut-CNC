"""Fokuskorrektur mit mehreren Höhenmeshes (verschieden hohe Werkstücke) –
zusammen mit Fokus-Absenkung je Durchgang (z_step) und 3D-Tiefe."""
from __future__ import annotations

import re

import numpy as np
import pytest

from lumacut_canvas.export import JobLayer
from lumacut_canvas.gcode import layers_to_gcode
from scanprobe.compensation import FocusSettings
from scanprobe.focus_export import compensate_for_export, precheck_gcode
from scanprobe.geometry import Rect
from scanprobe.heightmap import MEASURED, HeightMap, HeightMapSet

FOCUS = FocusSettings().focus_z(0.0)  # 5,5 mm über der Oberfläche
_W = re.compile(r"([XYZS])(-?[\d.]+)")


def _map(aid, rect, z):
    xs = np.arange(rect.xmin, rect.xmax + 0.1, 10.0)
    ys = np.arange(rect.ymin, rect.ymax + 0.1, 10.0)
    hm = HeightMap.empty(aid, rect.to_polygon(), xs, ys)
    for j in range(len(ys)):
        for i in range(len(xs)):
            hm.set(i, j, z, MEASURED)
    return hm


def two_heights(a=Rect(60, 60, 160, 160), za=2.0, b=Rect(220, 60, 320, 160), zb=6.0):
    return HeightMapSet([_map("a", a, za), _map("b", b, zb)])


def simulate(gcode):
    """(Abschnitt, Durchgang, x, y, z) je brennendem G1 + Prüfung der Eilfahrten."""
    x = y = 0.0
    z = None
    layer, npass = "", 1
    burns, lowered_after_rapid = [], []
    pending = False   # nach G0 XY: nächstes Z darf nicht höher sein (erst heben, dann fahren)
    for line in gcode.splitlines():
        if line.startswith(("; LAYER ", "; IMAGE ")):
            layer, npass = line[2:], 1
        elif line.startswith("; PASS "):
            npass = int(line.split()[2])
        if not line.startswith(("G0", "G1")):
            continue
        w = {k: float(v) for k, v in _W.findall(line)}
        if "Z" in w:
            if pending and z is not None and w["Z"] > z + 1e-6 and "X" not in w:
                lowered_after_rapid.append(line)
            z = w["Z"]
        if "X" in w or "Y" in w:
            x, y = w.get("X", x), w.get("Y", y)
            pending = line.startswith("G0")
            if line.startswith("G1") and w.get("S", 0) > 0:
                burns.append((layer, npass, x, y, z))
    return burns, lowered_after_rapid


def surface(x, y):
    return 2.0 if x < 190 else 6.0


def test_vectors_with_z_step_on_two_heights():
    src = layers_to_gcode([
        JobLayer("l1", "Tief", 80, 600, 3, [[(80, 80), (140, 80)], [(240, 80), (300, 80)]], z_step_mm=0.5),
        JobLayer("l2", "Gravur", 20, 3000, 1, [[(240, 120), (300, 120)], [(80, 120), (140, 120)]])])
    assert precheck_gcode(src) == []
    res = compensate_for_export(src, two_heights())
    assert res.ok, res.errors
    assert "G91" not in res.gcode
    burns, wrong = simulate(res.gcode)
    assert burns and wrong == []          # Eilfahrt in höheren Bereich: erst Z hoch, dann XY
    for layer, npass, x, y, z in burns:
        drop = 0.5 * (npass - 1) if "Tief" in layer else 0.0
        assert z == pytest.approx(surface(x, y) + FOCUS - drop, abs=0.03), (layer, npass, x, y)
    # beide Höhen in jedem Durchgang
    tief = {(p, surface(x, y)) for l, p, x, y, _ in burns if "Tief" in l}
    assert tief == {(p, s) for p in (1, 2, 3) for s in (2.0, 6.0)}
    assert res.report.z_min == pytest.approx(2 + FOCUS - 1.0, abs=0.01)
    assert res.report.z_max == pytest.approx(6 + FOCUS, abs=0.01)


def test_depth3d_image_across_adjacent_regions(qapp):
    """3D-Bild über zwei angrenzende Höhen: jede Stufe = lokale Oberfläche + Fokus − Absenkung."""
    from lumacut_canvas.model import Document, Geometry, Layer, Shape
    from lumacut_job.planner import optimized_document_gcode
    from test_focus_export import _image
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    # Arbeitsfläche 70..170 -> Maschine 100..200 (Grenze der Meshes bei X150)
    _image(d, 70, 70, 100, 40, mode="depth3d", line_interval_mm=1.0, overscan_mm=5,
           z_step_mm=0.3, depth_levels=4)
    d.add_shape(Shape("rect", Geometry(80, 115, 80, 10), d.active_layer_id))
    src = optimized_document_gcode(d)
    maps = two_heights(a=Rect(90, 90, 150, 160), za=2.0, b=Rect(150, 90, 210, 160), zb=3.5)
    res = compensate_for_export(src, maps)
    assert res.ok, res.errors
    assert res.coverage.outside_mm == 0
    burns, wrong = simulate(res.gcode)
    assert wrong == []
    surf = lambda x: 2.0 if x < 150 else 3.5
    steps = {0.0, -0.3, -0.6, -0.9}
    seen = set()
    for layer, _p, x, y, z in burns:
        if abs(x - 150) < 1e-6:
            continue                                # Grenzpunkt: beide Meshes gültig
        off = round(z - surf(x) - FOCUS, 2)
        if layer.startswith("IMAGE"):
            assert any(abs(off - s) < 0.03 for s in steps), (x, y, z)
            seen.add((surf(x), min(steps, key=lambda s: abs(off - s))))
        else:
            assert off == pytest.approx(0.0, abs=0.03), (layer, x, y, z)
    assert {s for s, _ in seen} == {2.0, 3.5}
    assert {o for _, o in seen} == steps
    assert res.report.focus_offset_min == pytest.approx(-0.9, abs=1e-3)
    assert res.report.z_min == pytest.approx(2 + FOCUS - 0.9, abs=0.01)


def test_height_difference_vs_pi_guard():
    """Pi prüft gegen eine Oberfläche (letztes G30): G30 auf dem höheren Werkstück
    sperrt den tieferen Bereich -> klarer Fehler statt Abbruch mitten im Auftrag."""
    src = layers_to_gcode([JobLayer("l1", "Tief", 80, 600, 2, [[(80, 80), (140, 80)], [(240, 80), (300, 80)]],
                                    z_step_mm=1.0)])
    maps = two_heights()
    bad = compensate_for_export(src, maps, pi_surface_z=6.0)
    assert not bad.ok and bad.gcode is None
    msg = " ".join(bad.errors)
    assert "Pi-Sperre Z8.00" in msg and "4.00 mm unter der Pi-Oberfläche" in msg
    assert "Fokus-Absenkung bis 1.00 mm" in msg and "niedrigsten Werkstück" in msg
    ok = compensate_for_export(src, maps, pi_surface_z=2.0)        # G30 auf dem tieferen Teil
    assert ok.ok, ok.errors
    # kleiner Höhenunterschied: auch G30 auf dem höheren Teil reicht
    near = compensate_for_export(src, two_heights(zb=3.0), pi_surface_z=3.0)
    assert near.ok, near.errors


def test_send_paths_with_two_heights(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_canvas.model import Geometry, Shape
    win = main.LumaCutStudio()
    try:
        sent = []
        monkeypatch.setattr(win.machine_panel, "send_gcode",
                            lambda name, gcode, start=False: sent.append((gcode, start)))
        doc = win.canvas.document
        doc.add_shape(Shape("rect", Geometry(50, 50, 40, 30), doc.active_layer_id))    # Maschine 80..120
        doc.add_shape(Shape("rect", Geometry(210, 50, 40, 30), doc.active_layer_id))   # Maschine 240..280
        sp = win.scan_panel
        sp.ask = False
        sp.set_maps(two_heights())
        pi_z = {"v": 2.0}
        monkeypatch.setattr(sp, "_pi_surface_z", lambda: pi_z["v"])
        win._send_canvas_job()
        assert len(sent) == 1
        burns, _ = simulate(sent[0][0])
        assert {round(z - surface(x, y), 2) for _, _, x, y, z in burns} == {round(FOCUS, 2)}
        assert {surface(x, y) for _, _, x, y, _ in burns} == {2.0, 6.0}
        # Workflow „Auftrag“: gleicher Hook, gleiche Prüfung
        win.workflow_adapter.confirm = lambda *_: True
        assert win.workflow_adapter._send_and_start()
        assert sent[-1][1] is True and sent[-1][0] == sent[0][0]
        pi_z["v"] = 6.0                                       # G30 auf dem hohen Teil
        win._send_canvas_job()
        assert not win.workflow_adapter._send_and_start()
        assert len(sent) == 2 and "Pi-Sperre" in sp.last_error
    finally:
        win.canvas.undo_stack.setClean()
        win.scan_panel.shutdown()
        win.close()
