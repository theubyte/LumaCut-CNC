"""„Markieren“: Probe-Bereiche aus Canvas, Scan-Overlay und Auswahl (offscreen, Simulation)."""
from __future__ import annotations

import pytest

from scanprobe.geometry import Rect
from scan_coords import screen_rect


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


def _scan(panel):
    assert panel.start_scan(), panel.last_error
    assert panel.wait(60000) and panel.last_error == ""


def _drag(editor, x, y, w, h):
    """Wie ein fertiger Mauszug im ROI-Modus (tools.py -> editor._roi_finished)."""
    from lumacut_canvas.workarea import Rect as CRect
    editor.tools.roi_pending = False
    editor._roi_finished(CRect(x, y, w, h))


def _checked(panel):
    return {o.id for o in panel.checked_objects()}


def test_tap_toggles_object_and_overlay_style(panel):
    _scan(panel)
    rect = [o for o in panel.objects if o.kind == "rectangle"][0]
    assert rect.id in _checked(panel)
    hits = []
    panel.areasChanged.connect(lambda: hits.append(1))
    cx, cy = rect.bounds.center
    assert panel.mark_rect(Rect(cx - 1, cy - 1, cx + 1, cy + 1)) == "toggle"
    assert rect.id not in _checked(panel) and hits
    item = [it for it in panel.overlay.object_items if it.data(0) == rect.id and hasattr(it, "brush")][0]
    assert item.brush().color().alpha() == 0
    assert panel.mark_rect(Rect(cx - 1, cy - 1, cx + 1, cy + 1)) == "toggle"
    assert rect.id in _checked(panel) and item.brush().color().alpha() > 0
    # Antippen ins Leere: nichts passiert
    assert panel.mark_rect(Rect(40, 40, 41, 41)) == "" and panel.manual_areas == []


def test_roi_from_canvas_checks_objects_or_adds_manual_area(panel, editor):
    from PySide6.QtCore import Qt
    from scanprobe.panel import Z_OVERLAY
    _scan(panel)
    rect = [o for o in panel.objects if o.kind == "rectangle"][0]
    circle = [o for o in panel.objects if o.kind == "circle"][0]
    panel._set_checked({rect.id, circle.id}, toggle=True)
    assert _checked(panel) == set()
    # Fremde ROI (z. B. Kamera-Ausschnitt) wird ignoriert
    _drag(editor, *screen_rect(60, 70, 140, 110))   # Maschinen-mm (§2.3)
    assert _checked(panel) == set()
    # Bereich um das Rechteck -> Werkstück angehakt, keine manuelle Fläche
    assert panel.start_marking() and editor.roi_pending
    _drag(editor, *screen_rect(60, 70, 140, 110))
    assert _checked(panel) == {rect.id} and panel.manual_areas == []
    assert not editor.roi_pending
    # Bereich auf leerer Fläche -> manueller Rechteck-Bereich
    assert panel.start_marking()
    _drag(editor, *screen_rect(40, 300, 50, 40))
    assert len(panel.manual_areas) == 1
    area = panel.manual_areas[0]
    assert area.source == "manual" and area.polygon.bounds == Rect(40, 300, 90, 340)
    items = panel.overlay.manual_items
    assert len(items) == 1 and items[0].scene() is editor.scene
    assert items[0].zValue() == Z_OVERLAY and items[0].acceptedMouseButtons() == Qt.MouseButton.NoButton
    areas, _ = panel.probe_areas()
    assert [a.id for a in areas] == [rect.id, area.id]
    assert "1 manuell" in panel.areas_label.text()
    # Abbrechen setzt den Markiermodus zurück
    assert panel.start_marking()
    editor.roiCancelled.emit()
    assert not panel._marking
    panel.clear_manual_areas()
    assert panel.manual_areas == [] and panel.overlay.manual_items == []


def test_manual_area_clipped_to_work_area(panel):
    a = panel.add_manual_area(Rect(10, 10, 60, 60).to_polygon())
    assert a is not None and a.polygon.bounds == Rect(30, 30, 60, 60)
    assert panel.add_manual_area(Rect(0, 0, 20, 20).to_polygon()) is None
    assert "außerhalb" in panel.last_error


def test_probe_manual_area_without_scan(panel):
    assert not panel.probe_button.isEnabled()
    panel.mark_rect(Rect(250, 200, 320, 300))      # über der Scheibe, aber kein Scan
    assert panel.probe_button.isEnabled()
    assert panel.start_probe() and panel.wait(60000), panel.last_error
    assert [m.area_id for m in panel.maps.maps] == ["m1"]
    # Design wird nur als Rückfall geprobt, solange nichts markiert ist
    assert all(a.source == "manual" for a in panel.probe_areas()[0])


def test_selection_becomes_polygon_area(panel, editor):
    from lumacut_canvas.model import Geometry, Shape
    from scanprobe.panel import machine_rect, to_machine
    doc = editor.document
    rect = doc.add_shape(Shape("rect", Geometry(100, 100, 40, 20), doc.active_layer_id))
    ell = doc.add_shape(Shape("ellipse", Geometry(200, 150, 40, 40), doc.active_layer_id))
    editor.set_selection([rect.id, ell.id])
    assert panel.add_selection_areas() == 2
    ra, ea = panel.manual_areas
    want = machine_rect(97, 97, 143, 123)      # Ecken sortiert (Nullpunkt oben rechts)
    b = ra.polygon.bounds
    assert (b.xmin, b.ymin, b.xmax, b.ymax) == pytest.approx((want.xmin, want.ymin, want.xmax, want.ymax))
    cx, cy = to_machine(220, 170)
    assert ea.polygon.contains(cx, cy) and ea.kind == "polygon"
    assert len(ea.polygon.points) > 8                   # Umriss, nicht nur Box
    assert ea.polygon.bounds.width == pytest.approx(46, abs=0.5)
    editor.set_selection([])
    assert panel.add_selection_areas() == 0 and "ausgewählt" in panel.last_error


def test_full_run_includes_manual_areas(panel):
    panel.design_only.setChecked(False)
    panel.mark_rect(Rect(40, 300, 90, 340))
    assert panel.start_full()
    assert panel.wait(60000) and panel.last_error == ""
    ids = [m.area_id for m in panel.maps.maps]
    assert len(ids) == 3 and "m1" in ids


@pytest.fixture()
def win(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.delenv("LUMACUT_KEY", raising=False)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    yield w
    w.canvas.undo_stack.setClean()
    w.scan_panel.shutdown()
    w.close()


def test_workflow_mark_step_starts_marking(win):
    from lumacut_workflow.steps import DONE, READY
    from scanprobe.panel import from_machine
    p, sp = win.workflow_panel, win.scan_panel
    p.adapter.marks.skip("scan")
    p.refresh()
    p.select("mark")
    assert p.state("mark").status == READY and p.run_button.text() == "Markieren"
    assert p.run_selected() and sp._marking and win.canvas.roi_pending
    x, y = from_machine(250, 200)
    _drag(win.canvas, x, y, 60.0, 80.0)
    assert len(sp.manual_areas) == 1
    assert p.state("mark").status == DONE
    assert p.state("probe").reason != "Keine markierten Bereiche"
