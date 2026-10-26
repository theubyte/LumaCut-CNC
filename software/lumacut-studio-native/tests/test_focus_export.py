"""Fokuskorrigierter G-Code-Export: Prüfungen, Rückfall, UI-Anbindung."""
from __future__ import annotations

import re
import time

import numpy as np
import pytest

from lumacut_canvas.export import JobLayer
from lumacut_canvas.gcode import layers_to_gcode
from scanprobe.compensation import FocusSettings
from scanprobe.focus_export import compensate_for_export, job_coverage, precheck_gcode
from scanprobe.geometry import Rect
from scanprobe.heightmap import MEASURED, HeightMap, HeightMapSet
from scanprobe.stitch import Mosaic
from scan_coords import add_rect_at_machine, gcode_rect

FOCUS = FocusSettings().focus_z(0.0)  # Fokus über Oberfläche (5,5 mm)


def fake_maps(rect=Rect(100, 100, 200, 200), z_fn=lambda x, y: 3.0 + 0.01 * x,
              created=None) -> HeightMapSet:
    xs = np.arange(rect.xmin, rect.xmax + 0.1, 10.0)
    ys = np.arange(rect.ymin, rect.ymax + 0.1, 10.0)
    hm = HeightMap.empty("a", rect.to_polygon(), xs, ys)
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            hm.set(i, j, z_fn(x, y), MEASURED)
    ms = HeightMapSet([hm])
    if created is not None:
        ms.created = created
    return ms


def job(*polylines, power=50, speed=1200, passes=1) -> str:
    return layers_to_gcode([JobLayer("l1", "Schnitt", power, speed, passes, [list(p) for p in polylines])])


def g1_lines(gcode):
    return [l for l in gcode.splitlines() if l.startswith("G1 ")]


def zs(gcode):
    return [float(m) for m in re.findall(r"Z(-?[\d.]+)", gcode)]


# ---------------------------------------------------------------- Kern
def test_compensated_export_inside_mesh():
    maps = fake_maps()
    src = job([(110, 110), (190, 110), (190, 190)])
    res = compensate_for_export(src, maps)
    assert res.ok, res.errors
    assert [w for w in res.warnings if "Kein aktueller Scan" not in w] == []
    assert res.coverage.outside_mm == 0
    out = res.gcode
    assert "M3 I" in out and out.rstrip().endswith("M400")
    # erstes brennendes G1 trägt Z explizit (Pi-Autofokus wird sofort übersteuert)
    assert "Z" in g1_lines(out)[0]
    # Z folgt der Oberfläche: Ende bei x=190 -> 3 + 1.9 + 5.5
    assert zs(out)[-1] == pytest.approx(3.0 + 1.9 + FOCUS, abs=0.03)
    assert min(zs(out)) >= 3.0 + 1.1 + 2.0  # nie unter Oberfläche + 2
    assert res.report.segments_added > 0
    assert "Fokuskorrektur angewendet" in res.summary()


def test_original_gcode_untouched():
    src = job([(110, 110), (190, 110)])
    before = str(src)
    compensate_for_export(src, fake_maps())
    assert src == before and "Z" not in src


def test_arcs_are_rejected_with_clear_message():
    src = "G21\nG90\nM3 I\nG0 X110 Y110\nG2 X150 Y150 I20 J20 F1200 S100\nM5 I\n"
    errs = precheck_gcode(src)
    assert errs and "G2/G3" in errs[0] and "Liniensegmente" in errs[0]
    res = compensate_for_export(src, fake_maps())
    assert not res.ok and res.gcode is None
    assert "nicht möglich" in res.summary()


def test_focus_step_down_is_added_to_mesh_z():
    """z_step (Fokus-Absenkung je Durchgang) wird auf das Mesh-Z aufgerechnet."""
    flat = fake_maps(z_fn=lambda x, y: 3.0)
    src = layers_to_gcode([JobLayer("l1", "Tief", 80, 600, 3, [[(110, 110), (150, 110)]], z_step_mm=0.5)])
    assert "G0 Z-0.500 F600" in src and precheck_gcode(src) == []
    res = compensate_for_export(src, flat)
    assert res.ok, res.errors
    out = res.gcode
    assert "G91" not in out and "Z-0.5" not in out          # nur absolute Z
    passes = out.split("; PASS ")[1:]
    first_z = [zs(p)[0] if zs(p) else None for p in passes]
    # Durchgang 1: Fokus, 2: −0,5, 3: −1,0 (ab erster Fahrt des Durchgangs)
    assert first_z == pytest.approx([3 + FOCUS, 3 + FOCUS - 0.5, 3 + FOCUS - 1.0], abs=0.01)
    assert res.report.focus_offset_min == pytest.approx(-1.0)
    assert "Fokus-Absenkung je Durchgang bis 1.00 mm" in res.summary()
    # Nächste Ebene startet wieder auf Fokushöhe
    two = layers_to_gcode([
        JobLayer("l1", "Tief", 80, 600, 2, [[(110, 110), (150, 110)]], z_step_mm=1.0),
        JobLayer("l2", "Gravur", 20, 3000, 1, [[(110, 150), (150, 150)]])])
    out2 = compensate_for_export(two, flat).gcode
    assert zs(out2.split("; LAYER Gravur")[1])[0] == pytest.approx(3 + FOCUS, abs=0.01)


def test_focus_step_down_never_below_clearance():
    src = layers_to_gcode([JobLayer("l1", "Tief", 80, 600, 4, [[(110, 110), (150, 110)]], z_step_mm=1.0)])
    res = compensate_for_export(src, fake_maps(), settings=FocusSettings(min_clearance_mm=4.0))
    assert not res.ok and any("unter Oberfläche + 4 mm" in e for e in res.errors)


def test_absolute_z_words_rejected():
    src = job([(110, 110), (190, 110)]).replace("G0 X110", "G0 Z12\nG0 X110", 1)
    res = compensate_for_export(src, fake_maps())
    assert not res.ok
    assert any("absoluter Z-Angabe" in e for e in res.errors)


def test_layers_with_different_power_speed_and_planner_order():
    """Aktueller Exporter mit Schnittplaner: S/F je Ebene bleiben erhalten."""
    from lumacut_job.planner import optimize_layers
    layers = [JobLayer("a", "Schnitt", 100, 300, 1, [[(110, 110), (190, 110), (190, 190), (110, 110)],
                                                      [(140, 140), (160, 140), (160, 160), (140, 140)]]),
              JobLayer("b", "Gravur", 25, 3000, 1, [[(120, 180), (180, 180)]])]
    src = layers_to_gcode(optimize_layers(layers))
    res = compensate_for_export(src, fake_maps())
    assert res.ok, res.errors
    out = res.gcode
    cut, engrave = out.split("; LAYER Gravur")
    assert {m for m in re.findall(r" S(\d+)", cut)} == {"255"}
    assert {m for m in re.findall(r" S(\d+)", engrave)} == {str(round(0.25 * 255))}
    assert "F300" in cut and "F3000" in engrave
    # Reihenfolge der Ebenen/Polylinien unverändert (Startpunkte der G0)
    starts = lambda g: [tuple(float(v) for v in re.findall(r"[XY](-?[\d.]+)", l))
                        for l in g.splitlines() if l.startswith("G0 X")]
    assert starts(out) == starts(src)


def test_material_test_grid_with_hatch(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    from lumacut_canvas.model import Document
    from lumacut_job.material_test import MaterialTestSpec, add_material_test
    doc = Document()
    add_material_test(doc, MaterialTestSpec(columns=3, rows=2, line_interval_mm=1.0))
    src = document_to_gcode(doc)
    maps = fake_maps(rect=gcode_rect(src), z_fn=lambda x, y: 4.0)
    res = compensate_for_export(src, maps)
    assert res.ok, res.errors
    assert res.coverage.outside_mm == 0
    assert all(z == pytest.approx(4 + FOCUS) for z in zs(res.gcode))
    assert len(set(re.findall(r" S(\d+)", res.gcode))) >= 3       # Leistung je Zelle erhalten


def test_outside_mesh_uses_highest_surface_and_warns():
    maps = fake_maps()   # höchste Oberfläche: x=200 -> 5.0
    src = job([(150, 150), (250, 150)])  # halb außerhalb
    res = compensate_for_export(src, maps)
    assert res.ok, res.errors
    cov = res.coverage
    assert cov.burn_mm == pytest.approx(100, abs=0.5)
    assert 0.35 < cov.outside_fraction < 0.5   # Kante hat 6 mm Toleranz
    assert any("außerhalb der geprobten Bereiche" in w and "Z5.00" in w for w in res.warnings)
    assert res.fallback_surface_z == pytest.approx(5.0)
    # letztes Segment (x=250) liegt außerhalb -> Fokus der höchsten Oberfläche
    assert zs(res.gcode)[-1] == pytest.approx(5.0 + FOCUS, abs=0.03)


def test_job_completely_outside_is_error():
    res = compensate_for_export(job([(300, 300), (350, 300)]), fake_maps())
    assert not res.ok and any("Keine Brennstrecke" in e for e in res.errors)


def test_no_maps_is_error():
    res = compensate_for_export(job([(110, 110), (150, 110)]), None)
    assert not res.ok and "Höhenmesh messen" in res.errors[0]


def test_old_mesh_warns():
    maps = fake_maps(created=time.time() - 10 * 3600)
    res = compensate_for_export(job([(110, 110), (150, 110)]), maps)
    assert res.ok and any("h alt" in w for w in res.warnings)


def test_pi_surface_guard_blocks():
    """Pi bricht Z-Fahrten unter (G30-Oberfläche + 2 mm) mitten im Lauf ab -> vorher Fehler."""
    res = compensate_for_export(job([(110, 110), (150, 110)]), fake_maps(), pi_surface_z=8.0)
    assert not res.ok and res.gcode is None
    assert any("Pi-Sperre" in e and "mitten im Lauf" in e and "G30" in e for e in res.errors)
    res = compensate_for_export(job([(110, 110), (150, 110)]), fake_maps(), pi_surface_z=3.0)
    assert res.ok and not any("Pi-Sperre" in w for w in res.warnings + res.errors)


def _mosaic(shift_px=0):
    rng = np.random.default_rng(3)
    small = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
    import cv2
    img = cv2.resize(small, (400, 400), interpolation=cv2.INTER_CUBIC)
    img = np.roll(img, shift_px, axis=1)
    return Mosaic(img, 0.5, (50.0, 50.0), np.ones((400, 400), bool))


def test_fingerprint_against_current_scan():
    maps = fake_maps()
    src = job([(110, 110), (150, 110)])
    res = compensate_for_export(src, maps, mosaic=_mosaic())
    assert res.ok and any("Fingerabdruck" in w for w in res.warnings)   # keiner vorhanden
    maps.add_fingerprints(_mosaic())
    res = compensate_for_export(src, maps, mosaic=_mosaic())
    assert res.ok and not any("Fingerabdruck" in w or "Scan" in w for w in res.warnings)
    res = compensate_for_export(src, maps, mosaic=_mosaic(shift_px=12))   # 6 mm verschoben
    assert not res.ok and any("neu proben" in e for e in res.errors)
    res = compensate_for_export(src, maps)   # kein aktueller Scan
    assert res.ok and any("Kein aktueller Scan" in w for w in res.warnings)


def test_job_coverage_ignores_rapids():
    cov = job_coverage(job([(110, 110), (150, 110)], [(300, 300), (310, 300)]), fake_maps())
    assert cov.burn_mm == pytest.approx(50, abs=0.5)
    assert cov.outside_mm == pytest.approx(10, abs=0.5)


# ---------------------------------------------------------------- UI
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


def _add_rect(editor, x, y, w, h):
    from lumacut_canvas.model import Geometry, Shape
    editor.document.add_shape(Shape("rect", Geometry(x, y, w, h), editor.document.active_layer_id))


def test_focus_correction_is_automatic_with_mesh(panel, editor, tmp_path):
    """Anforderungen 2026-10-26 §1: keine Auswahl mit/ohne Höhenmesh mehr."""
    from lumacut_job.planner import optimized_document_gcode as document_to_gcode
    assert not hasattr(panel, "focus_check") and not hasattr(panel, "focus_hint")
    add_rect_at_machine(editor, 110, 110, 40, 30)   # Maschine 110..150 / 110..140
    plain = document_to_gcode(editor.document)
    assert panel.prepare_job_gcode(plain) == plain          # ohne Mesh: der Auftrag misst selbst
    p = tmp_path / "a.gcode"
    assert panel.export_gcode(p) and p.read_text() == plain
    # Mesh vorhanden -> immer korrigiert, ohne Haken
    panel.set_maps(fake_maps())
    assert panel.export_gcode(p)
    out = p.read_text()
    assert out != plain and "Fokuskorrektur" in out and zs(out)
    assert panel.last_focus_export.ok
    # Verstecktes Experten-/Test-Schalterchen
    panel.skip_focus_correction = True
    assert panel.prepare_job_gcode(plain) == plain
    panel.skip_focus_correction = False
    # Mesh weg -> wieder unkorrigiert
    panel.clear()
    assert panel.export_gcode(p) and p.read_text() == plain


def test_stale_mesh_is_an_error_not_a_question(panel, editor):
    import time
    from lumacut_job.planner import optimized_document_gcode as document_to_gcode
    add_rect_at_machine(editor, 110, 110, 40, 30)
    panel.set_maps(fake_maps(created=time.time() - 48 * 3600))
    assert panel.prepare_job_gcode(document_to_gcode(editor.document)) is None
    assert "alt" in panel.last_error and "neu messen" in panel.last_error


def test_focus_export_error_blocks_export(panel, editor, tmp_path):
    _add_rect(editor, 300, 300, 20, 20)   # weit außerhalb des Meshes
    panel.set_maps(fake_maps())
    p = tmp_path / "b.gcode"
    assert not panel.export_gcode(p) and not p.exists()
    assert "Keine Brennstrecke" in panel.last_error


def test_end_to_end_scan_probe_export(panel, editor, tmp_path):
    panel.design_only.setChecked(False)
    assert panel.start_scan() and panel.wait(60000) and panel.last_error == ""
    assert panel.start_probe() and panel.wait(60000) and panel.last_error == ""
    assert panel.maps.fingerprints            # beim Proben angelegt
    # Design auf dem schrägen Rechteck-Werkstück (Maschine 70..190 / 80..170)
    add_rect_at_machine(editor, 90, 100, 60, 40)
    p = tmp_path / "c.gcode"
    assert panel.export_gcode(p), panel.last_error
    res = panel.last_focus_export
    assert res.ok and res.coverage.outside_mm == 0
    assert not any("neu proben" in w for w in res.warnings)
    # Fokus = Oberfläche (3 + 0.008(x-70) + 0.004(y-80)) + 5.5 an der Startecke
    # (X90 oder X150 je nach Nullpunkt, Y100)
    lines = p.read_text().splitlines()
    first = [l for l in lines if l.startswith("G0 Z")][0]
    sx, sy = (float(v) for v in re.findall(r"[XY](-?[\d.]+)", [l for l in lines if l.startswith("G0 X")][0]))
    assert (round(sx), round(sy)) in {(90, 100), (150, 100)}
    assert float(first[4:]) == pytest.approx(3 + 0.008 * (sx - 70) + 0.004 * (sy - 80) + FOCUS, abs=0.1)


def test_main_window_send_uses_focus_option(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_job.planner import optimized_document_gcode as document_to_gcode
    win = main.LumaCutStudio()
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda name, gcode, start=False: sent.append(gcode))
    add_rect_at_machine(win.canvas, 110, 110, 40, 30)
    plain = document_to_gcode(win.canvas.document)
    win._send_canvas_job()
    assert sent[-1] == plain                            # ohne Mesh unverändert
    win.scan_panel.ask = False
    win.scan_panel.set_maps(fake_maps())
    win._send_canvas_job()
    assert sent[-1] != plain and "Fokuskorrektur" in sent[-1]
    win.scan_panel.set_maps(fake_maps(rect=Rect(300, 300, 350, 350)))   # passt nicht
    win._send_canvas_job()
    assert len(sent) == 2                               # Fehler -> nichts gesendet
    win.canvas.undo_stack.setClean()
    win.close()


def test_scan_overlay_with_current_canvas(panel, editor):
    """Overlay über vielen Ebenen (Materialtest), nicht anwählbar, ohne Undo-Einträge, Zoom ok."""
    from PySide6.QtCore import QPointF
    from lumacut_job.material_test import MaterialTestSpec
    from lumacut_job.qt_tools import insert_material_test
    from scanprobe.panel import Z_OVERLAY
    insert_material_test(editor, MaterialTestSpec(columns=5, rows=5))
    undo_before = editor.undo_stack.count()
    panel.design_only.setChecked(False)
    assert panel.start_scan() and panel.wait(60000)
    assert panel.start_probe() and panel.wait(60000) and panel.last_error == ""
    assert editor.undo_stack.count() == undo_before          # Scan/Probe ändert das Dokument nicht
    shape_z = max(it.zValue() for it in editor.scene.items_by_id.values())
    heat = panel.overlay.heat_item
    assert heat is not None and heat.zValue() > shape_z
    assert all(it.zValue() > shape_z for it in panel.overlay.object_items)
    assert Z_OVERLAY < 1e9                                      # Auswahlrahmen bleibt oben
    # Klick auf ein Objekt unter dem Overlay trifft das Objekt, nicht die Heatmap
    shape = editor.document.shapes[-1]
    g = shape.geom
    sid = editor.scene.editable_shape_at(QPointF(g.x + g.w / 2, g.y + g.h / 2))
    assert sid is not None and editor.document.has_shape(sid)
    editor.select_all()
    assert set(editor.selection) == {s.id for s in editor.document.shapes}
    # Zoom (Auswahl-Anker) und Einpassen lassen das Overlay an Ort und Stelle
    before = heat.sceneBoundingRect()
    editor.view.zoom_wheel(1.5, QPointF(50, 50))
    editor.fit_selection()
    assert heat.sceneBoundingRect() == before and heat.scene() is editor.scene
    # Undo/Redo entfernt bzw. erneuert Formen, Overlay bleibt
    editor.undo_stack.undo()
    assert heat.scene() is editor.scene and editor.document.shapes == []
    editor.undo_stack.redo()
    assert heat.scene() is editor.scene and editor.document.shapes


def test_relief_raster_with_layer_step_down():
    """Schichten-Relief (Raster, S0-Lücken, z_step) aus lumacut_materials läuft durch die Korrektur."""
    pytest.importorskip("lumacut_materials")
    from lumacut_materials.db import load_db
    from lumacut_materials.heightmap import HeightmapOptions, heightmap_from_gray
    from lumacut_materials.planner import plan_relief
    from lumacut_materials.relief import job_from_plan, relief_to_gcode
    yy, xx = np.mgrid[0:60, 0:60]
    dome = np.clip(np.hypot(xx - 30, yy - 30) / 30, 0, 1)
    hm = heightmap_from_gray(dome, HeightmapOptions(width_mm=12, line_interval_mm=0.2,
                                                    depth_mm=2.0, blur_mm=0.2))
    rjob = job_from_plan(plan_relief(load_db(), "basswood_solid", 2.0), hm, 80.0, 80.0)
    assert rjob.z_step_mm > 0
    code, _ = relief_to_gcode(rjob)
    res = compensate_for_export(code, fake_maps(rect=gcode_rect(code), z_fn=lambda x, y: 3.0))
    assert res.ok, res.errors
    drop = rjob.z_step_mm * (rjob.layers - 1)
    assert res.report.focus_offset_min == pytest.approx(-drop, abs=1e-3)
    assert res.report.z_min == pytest.approx(3 + FOCUS - drop, abs=0.01)
    assert "G91" not in res.gcode


# ------------------------------------------------------- Bildobjekte (Raster/3D)
def _image(doc, x, y, w, h, **settings):
    from PySide6.QtGui import QColor, QImage
    from lumacut_canvas.model import Geometry, ImageSettings, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    img = QImage(40, 20, QImage.Format_RGB32)
    for px in range(40):
        for py in range(20):
            v = int(255 * px / 39)
            img.setPixelColor(px, py, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    sh = Shape("image", Geometry(x, y, w, h), doc.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    doc.add_shape(sh)
    return sh


def _union_mesh_rect(doc):
    from lumacut_canvas.workarea import to_machine
    bs = [s.bounds() for s in doc.shapes]
    ax, ay = to_machine(min(b.x for b in bs), min(b.y for b in bs))
    bx, by = to_machine(max(b.x + b.w for b in bs), max(b.y + b.h for b in bs))
    # Nullpunkt oben rechts (Anforderungen 2026-10-26 §2.3): X kann gespiegelt sein
    return Rect(min(ax, bx) - 1, min(ay, by) - 1, max(ax, bx) + 1, max(ay, by) + 1)


@pytest.mark.parametrize("mode", ["grayscale", "floyd", "depth3d"])
def test_image_jobs_through_focus_compensation(qapp, mode):
    """Bild-Raster/3D-Tiefe aus dem Planer: S0-Overscan zählt nicht als Brennstrecke,
    3D-Fokusabsenkung wird auf das Mesh-Z aufgerechnet, Vektorebene startet wieder im Fokus."""
    from lumacut_canvas.model import Document, Geometry, Layer, Shape
    from lumacut_job.planner import optimized_document_gcode
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    extra = {"z_step_mm": 0.3, "depth_levels": 4} if mode == "depth3d" else {}
    _image(d, 80, 80, 40, 20, mode=mode, line_interval_mm=0.5, overscan_mm=5, **extra)
    d.add_shape(Shape("rect", Geometry(90, 110, 20, 20), d.active_layer_id))
    src = optimized_document_gcode(d)
    assert precheck_gcode(src) == []
    flat = fake_maps(rect=_union_mesh_rect(d), z_fn=lambda x, y: 3.0)
    res = compensate_for_export(src, flat)
    assert res.ok, res.errors
    assert res.coverage.outside_mm == 0          # Overscan (S0) liegt außerhalb, zählt aber nicht
    out = res.gcode
    assert "G91" not in out and out.index("; IMAGE") < out.index("; LAYER")
    drop = 0.3 * 3 if mode == "depth3d" else 0.0
    assert res.report.focus_offset_min == pytest.approx(-drop, abs=1e-3)
    assert res.report.z_min == pytest.approx(3 + FOCUS - drop, abs=0.01)
    after = zs(out.split("; LAYER")[1])   # Z wird nur bei Änderung ausgegeben
    assert all(z == pytest.approx(3 + FOCUS, abs=0.01) for z in after)
    assert after or mode != "depth3d"


def test_scan_overlay_with_image_object(panel, editor):
    """Bildobjekt: Probe-Bereich aus seinen Grenzen, Overlay darüber, Klick/Touch trifft das Bild."""
    from PySide6.QtCore import QPointF
    sh = _image(editor.document, 80, 80, 40, 20, mode="grayscale", line_interval_mm=0.5)
    editor.documentChanged.emit()
    (b,) = panel.design_bounds()
    assert b.xmax - b.xmin == pytest.approx(40, abs=0.01) and b.ymax - b.ymin == pytest.approx(20, abs=0.01)
    panel.design_only.setChecked(True)
    assert panel.start_scan() and panel.wait(60000)
    assert panel.start_probe() and panel.wait(60000) and panel.last_error == ""
    assert panel.maps is not None and panel.maps.map_for((b.xmin + b.xmax) / 2, (b.ymin + b.ymax) / 2)
    img_item = editor.scene.items_by_id[sh.id]
    assert panel.overlay.heat_item.zValue() > img_item.zValue()
    centre = QPointF(100, 90)
    assert editor.scene.editable_shape_at(centre) == sh.id
    editor.set_touch_mode(True, persist=False)
    try:
        assert editor.scene.editable_shape_at(centre) == sh.id
        assert not editor.view._empty_background(QPointF(editor.view.mapFromScene(centre)))
    finally:
        editor.set_touch_mode(False, persist=False)


def test_scan_export_matches_send_with_selection_only(qapp, monkeypatch, tmp_path):
    """Scan-Export nutzt dieselbe Auftragsquelle wie „An Pi senden“ (Nur Auswahl)."""
    from PySide6.QtCore import QSettings
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job.estimate import estimate_gcode
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    panel = win.scan_panel
    panel.ask = False
    doc = win.canvas.document
    lid = doc.active_layer_id
    a = add_rect_at_machine(doc, 110, 110, 40, 30)   # Maschine 110..150 (im Mesh)
    add_rect_at_machine(doc, 170, 110, 40, 30)
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda n, g, start=False: sent.append(g))
    win.job_tools.set_selection_only(True)
    win.canvas.set_selection([a.id])
    out = tmp_path / "auswahl.gcode"
    assert panel.export_gcode(out)
    assert estimate_gcode(out.read_text()).cut_length_mm == pytest.approx(140, rel=0.01)
    win._send_canvas_job()
    assert sent and sent[-1] == out.read_text()          # Datei == gesendeter Auftrag
    # Mit Fokuskorrektur: ebenfalls nur die Auswahl, identisch zum Senden
    panel.set_maps(fake_maps())
    assert panel.export_gcode(out)
    corrected = out.read_text()
    assert "Fokuskorrektur" in corrected and zs(corrected)
    win._send_canvas_job()
    assert sent[-1] == corrected
    # Nur Auswahl ohne Auswahl: Export bricht mit Meldung ab
    win.canvas.set_selection([])
    assert not panel.export_gcode(tmp_path / "leer.gcode")
    assert not (tmp_path / "leer.gcode").exists()
    win.job_tools.set_selection_only(False)
    win.canvas.undo_stack.setClean()
    win.close()


def test_scan_export_custom_job_source(panel, editor, tmp_path):
    calls = []
    panel.job_gcode_source = lambda: (calls.append(1) or "G21\nG90\n", "Hinweis")
    p = tmp_path / "q.gcode"
    assert panel.export_gcode(p) and p.read_text() == "G21\nG90\n" and calls == [1]
