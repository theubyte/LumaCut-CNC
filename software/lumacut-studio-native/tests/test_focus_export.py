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


def test_z_words_rejected_e_g_focus_drop_layers():
    src = job([(110, 110), (190, 110)], passes=2).replace(
        "; PASS 2 OF 2", "G91\nG0 Z-0.500 F600\nG90\n; PASS 2 OF 2")
    res = compensate_for_export(src, fake_maps())
    assert not res.ok
    assert any("Fokus-Absenkung" in e for e in res.errors)


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
    assert not res.ok and "Auto-Probe" in res.errors[0]


def test_old_mesh_warns():
    maps = fake_maps(created=time.time() - 10 * 3600)
    res = compensate_for_export(job([(110, 110), (150, 110)]), maps)
    assert res.ok and any("h alt" in w for w in res.warnings)


def test_pi_surface_guard_warning():
    res = compensate_for_export(job([(110, 110), (150, 110)]), fake_maps(), pi_surface_z=8.0)
    assert res.ok and any("Pi-Sperre" in w for w in res.warnings)
    res = compensate_for_export(job([(110, 110), (150, 110)]), fake_maps(), pi_surface_z=3.0)
    assert not any("Pi-Sperre" in w for w in res.warnings)


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


def test_focus_option_disabled_without_mesh(panel, editor, tmp_path):
    from lumacut_canvas.gcode import document_to_gcode
    assert not panel.focus_check.isEnabled() and not panel.focus_check.isChecked()
    assert "Auto-Probe" in panel.focus_hint.text()
    _add_rect(editor, 80, 80, 40, 30)   # Maschine 110..150 / 110..140
    plain = document_to_gcode(editor.document)
    assert panel.prepare_job_gcode(plain) == plain          # Standard: unverändert
    p = tmp_path / "a.gcode"
    assert panel.export_gcode(p) and p.read_text() == plain
    # Mesh laden -> Option verfügbar, Export korrigiert
    panel.set_maps(fake_maps())
    assert panel.focus_check.isEnabled() and panel.focus_hint.text() == ""
    panel.focus_check.setChecked(True)
    assert panel.export_gcode(p)
    out = p.read_text()
    assert out != plain and "Fokuskorrektur" in out and zs(out)
    assert panel.last_focus_export.ok
    # Mesh weg -> Haken fällt weg, wieder unkorrigiert
    panel.clear()
    assert not panel.focus_check.isChecked() and not panel.focus_check.isEnabled()
    assert panel.export_gcode(p) and p.read_text() == plain


def test_focus_export_error_blocks_export(panel, editor, tmp_path):
    _add_rect(editor, 300, 300, 20, 20)   # weit außerhalb des Meshes
    panel.set_maps(fake_maps())
    panel.focus_check.setChecked(True)
    p = tmp_path / "b.gcode"
    assert not panel.export_gcode(p) and not p.exists()
    assert "Keine Brennstrecke" in panel.last_error


def test_end_to_end_scan_probe_export(panel, editor, tmp_path):
    panel.design_only.setChecked(False)
    assert panel.start_scan() and panel.wait(60000) and panel.last_error == ""
    assert panel.start_probe() and panel.wait(60000) and panel.last_error == ""
    assert panel.maps.fingerprints            # beim Proben angelegt
    # Design auf dem schrägen Rechteck-Werkstück (Maschine 70..190 / 80..170)
    _add_rect(editor, 60, 70, 60, 40)
    panel.focus_check.setChecked(True)
    p = tmp_path / "c.gcode"
    assert panel.export_gcode(p), panel.last_error
    res = panel.last_focus_export
    assert res.ok and res.coverage.outside_mm == 0
    assert not any("neu proben" in w for w in res.warnings)
    # Fokus = Oberfläche (3 + 0.008(x-70) + 0.004(y-80)) + 5.5 an der Startecke X90 Y100
    first = [l for l in p.read_text().splitlines() if l.startswith("G0 Z")][0]
    assert float(first[4:]) == pytest.approx(3 + 0.008 * 20 + 0.004 * 20 + FOCUS, abs=0.1)


def test_main_window_send_uses_focus_option(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_canvas.gcode import document_to_gcode
    win = main.LumaCutStudio()
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda name, gcode, start=False: sent.append(gcode))
    _add_rect(win.canvas, 80, 80, 40, 30)
    plain = document_to_gcode(win.canvas.document)
    win._send_canvas_job()
    assert sent[-1] == plain                            # Standard unverändert
    win.scan_panel.ask = False
    win.scan_panel.set_maps(fake_maps())
    win.scan_panel.focus_check.setChecked(True)
    win._send_canvas_job()
    assert sent[-1] != plain and "Fokuskorrektur" in sent[-1]
    win.scan_panel.set_maps(fake_maps(rect=Rect(300, 300, 350, 350)))   # passt nicht
    win.scan_panel.focus_check.setChecked(True)
    win._send_canvas_job()
    assert len(sent) == 2                               # Fehler -> nichts gesendet
    win.canvas.undo_stack.setClean()
    win.close()
