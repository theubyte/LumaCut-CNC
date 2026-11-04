"""Park corner drawn on the canvas as a no-go zone (lumacut_job.park_zone)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

from lumacut_canvas.workarea import WORK_WIDTH_MM, Rect, screen_to_machine
from lumacut_job import park_corner as pc
from lumacut_job import park_zone as pz


def test_default_zone_is_strip_top_right():
    r = pz.park_zone_rect()
    # head v6: machine X0..78 / Y0..35, work area starts at 30 mm
    assert r == Rect(WORK_WIDTH_MM - 48.0, 0.0, 48.0, 5.0)
    # its corners map back into the machine corner
    for x, y in ((r.x, r.y), (r.right, r.bottom)):
        mx, my = screen_to_machine(x, y)
        assert 30.0 - 1e-9 <= mx <= 78.0 + 1e-9 and 30.0 - 1e-9 <= my <= 35.0 + 1e-9


@pytest.mark.parametrize("corner", [(30.0, 80.0), (100.0, 30.0), (20.0, 20.0), (0.0, 50.0),
                                    (-5.0, 40.0)])
def test_corner_inside_safe_zone_is_invisible(corner):
    assert pz.park_zone_rect(corner) is None


def test_huge_corner_is_clamped_to_work_area():
    r = pz.park_zone_rect((1000.0, 1000.0))
    assert r == Rect(0.0, 0.0, 360.0, 340.0)


def test_hatch_lines_stay_inside_and_are_45_degrees():
    r = Rect(312.0, 0.0, 48.0, 5.0)
    lines = pz.hatch_lines(r, 2.0)
    assert len(lines) == pytest.approx((48 + 5) / 2, abs=1)
    for x0, y0, x1, y1 in lines:
        for x, y in ((x0, y0), (x1, y1)):
            assert r.x - 1e-9 <= x <= r.right + 1e-9 and r.y - 1e-9 <= y <= r.bottom + 1e-9
        assert (x1 - x0) == pytest.approx(-(y1 - y0))
    assert pz.hatch_lines(Rect(0, 0, 0, 5)) == [] and pz.hatch_lines(r, 0) == []


def test_object_hits_zone():
    assert pz.object_hits_zone(Rect(330, 2, 10, 10))
    assert not pz.object_hits_zone(Rect(330, 5, 10, 10))        # touching the lower edge
    assert not pz.object_hits_zone(Rect(200, 0, 100, 100))      # left of the zone
    assert not pz.object_hits_zone(Rect(330, 2, 10, 10), (20.0, 20.0))


def test_zone_matches_park_check_refusal():
    """A motif inside the drawn zone is what the send-time check refuses (absolute)."""
    from lumacut_canvas.workarea import machine_to_screen
    r = pz.park_zone_rect()
    inside = screen_to_machine(r.x + r.w / 2, r.y + r.h / 2)
    outside = screen_to_machine(r.x - 5.0, r.y + r.h / 2)
    def job(m):
        x, y = m
        return f"G90\nG0 X{x:.3f} Y{y:.3f}\nM4 S0\nG1 X{x + 1:.3f} Y{y + 1:.3f} F1500 S500\nM5\n"
    assert not pc.check_job(job(inside)).ok
    assert pc.check_job(job(outside)).ok
    assert machine_to_screen(*inside)[0] == pytest.approx(r.x + r.w / 2)


def _render(overlay, scale=4.0):
    img = QImage(int(360 * scale), int(340 * scale), QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setTransform(QTransform.fromScale(scale, scale))
    overlay.paint(p, QRectF(0, 0, 360, 340))
    p.end()
    return img


def test_overlay_paints_red_only_in_zone(qapp):
    img = _render(pz.ParkZoneOverlay())
    s = 4.0
    inside = QColor(img.pixel(int(335 * s), int(2.5 * s)))
    assert inside.red() > inside.green() + 20                      # reddish tint
    for x, y in ((300, 2.5), (335, 8), (100, 100)):
        assert QColor(img.pixel(int(x * s), int(y * s))) == QColor("white")


def test_overlay_without_visible_zone_paints_nothing(qapp):
    img = _render(pz.ParkZoneOverlay((20.0, 20.0)))
    assert all(QColor(img.pixel(x, y)) == QColor("white")
               for x in range(0, img.width(), 97) for y in range(0, img.height(), 89))


class FakePanel(QObject):
    status_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._status = None
        self.origin = "absolute"

    def job_origin(self):
        return self.origin, "tr"


class FakeEditor:
    def __init__(self):
        self.overlays = {}
        self.refreshed = 0

    def add_overlay(self, key, ov, z=0.0):
        self.overlays[key] = (ov, z)

    def refresh_overlays(self):
        self.refreshed += 1


def test_sync_follows_pi_corner_and_origin(qapp):
    ed, mp = FakeEditor(), FakePanel()
    sync = pz.install_park_zone(ed, mp)
    ov, z = ed.overlays[pz.OVERLAY_KEY]
    assert ov is sync.overlay and z == pz.OVERLAY_Z
    assert ov.visible and ov.corner == pc.PARK_CORNER_MM
    n = ed.refreshed
    mp.status_changed.emit(None)                       # nothing changed: no redraw
    assert ed.refreshed == n
    mp._status = SimpleNamespace(raw={"park_corner_mm": {"x": 90, "y": 50}})
    mp.status_changed.emit(mp._status)
    assert ov.corner == (90.0, 50.0) and ed.refreshed == n + 1
    assert ov.rect == Rect(300.0, 0.0, 60.0, 20.0)
    mp.origin = "user"                                 # placed job: canvas position irrelevant
    mp.status_changed.emit(mp._status)
    assert not ov.visible
    mp.origin = "absolute"
    assert sync.update() and ov.visible


def test_sync_without_panel_uses_mirror(qapp):
    ed = FakeEditor()
    sync = pz.install_park_zone(ed, None)
    assert sync.overlay.visible and sync.overlay.corner == pc.PARK_CORNER_MM


def test_job_tools_install_zone_on_real_canvas(qapp):
    from PySide6.QtWidgets import QMainWindow
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.qt_tools import JobTools
    from machine.panel import MachinePanel
    win = QMainWindow()
    ed = CanvasEditor()
    mp = MachinePanel()
    try:
        tools = JobTools(win, ed, mp, win.statusBar())
        assert tools.park_zone is not None
        assert ed.view.overlay(pz.OVERLAY_KEY) is tools.park_zone.overlay
        assert tools.park_zone.overlay.visible          # not connected: absolute
        # changing the panel's origin combo hides / shows it again (older Pi: stays absolute)
        mp.origin_combo.setCurrentIndex(max(0, mp.origin_combo.count() - 1))
        assert tools.park_zone.overlay.visible == (mp.job_origin()[0] == "absolute")
    finally:
        mp.shutdown() if hasattr(mp, "shutdown") else None
        ed.undo_stack.setClean()
        ed.close()
        win.close()
        ed.deleteLater()
        win.deleteLater()
        qapp.processEvents()
