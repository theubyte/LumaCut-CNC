"""Park-corner preflight in Studio (Pi 9ae8577): same refusal as the Pi, earlier."""
from __future__ import annotations

import pathlib
import random
import sys
from types import SimpleNamespace

import pytest

from lumacut_job import park_corner as pc

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import placement as pi_place, transport as pi_tr  # noqa: E402

TRAVELS = {"x": 390.0, "y": 370.0}


def rect(x0, y0, x1, y1, s=500):
    return "\n".join(["G90", f"G0 X{x0} Y{y0}", "M4 S0", f"G1 X{x1} Y{y0} F1500 S{s}",
                      f"G1 X{x1} Y{y1}", f"G1 X{x0} Y{y1}", f"G1 X{x0} Y{y0}", "M5"]) + "\n"


def pi_accepts(gcode, corner=pi_tr.PARK_CORNER_MM, dx=0.0, dy=0.0):
    placed = pi_place.translate(gcode.splitlines(), dx, dy)
    try:
        pi_place.check_extent(placed, TRAVELS, corner)
    except ValueError:
        return False
    return True


def test_mirror_matches_pi_source():
    assert pc.PARK_CORNER_MM == tuple(pi_tr.PARK_CORNER_MM)
    t = pi_tr.MarlinTransport("/dev/null")
    assert tuple(t.park_corner) == pc.PARK_CORNER_MM
    assert pc.ANCHORS == pi_place.ANCHORS and pc.COORD_CONVENTION == pi_place.COORD_CONVENTION


@pytest.mark.parametrize("gcode", [
    rect(40, 40, 90, 80),
    "G0 X100 Y100\nG1 X120 Y100 S0\nG1 X130 Y110 S300\nG1 X140 Y90\nG0 X10 Y10\nG1 X12 Y12\n",
    "G0 X100 Y100\nM3 S0\nG2 X120 Y100 I10 J0 S400\nG3 X100 Y100 R10\nM5\n",
    "G0 X50 Y50\nG1 X60 S200\nG91\nG1 X5 Y5\nG90\nG1 X70 Y70\nM5\nG1 X200 Y200\n",
    "G28\nG91\nG1 X40 Y40 S100\nG1 X10\n",
    "; only travel\nG0 X10 Y10\nG0 X200 Y200\n",
    "g1 x80 y40 s100 ; lower case\n(comment) G1 X90 Y50\n",
])
def test_powered_bounds_equal_pi_scan(gcode):
    _, pi_box = pi_place.scan(gcode.splitlines())
    box = pc.powered_bounds(gcode)
    if pi_box is None:
        assert box is None
    else:
        assert box == pytest.approx(pc.Box(pi_box.xmin, pi_box.ymin, pi_box.xmax, pi_box.ymax))


def test_anchor_point_equals_pi():
    box = pc.Box(40.0, 50.0, 90.0, 80.0)
    pbox = pi_place.Box(40.0, 50.0, 90.0, 80.0)
    for a in pc.ANCHORS:
        assert pc.anchor_point(box, a) == pi_place.anchor_point(pbox, a)
    with pytest.raises(ValueError):
        pc.anchor_point(box, "xx")


def test_visible_anchor_inverts_wire_anchor():
    from machine.client import wire_anchor
    for conv in (None, "origin_top_right", "other"):
        for a in pc.ANCHORS:
            assert pc.visible_anchor(wire_anchor(a, conv), conv) == a


def test_absolute_check_agrees_with_pi_randomly():
    rnd = random.Random(11)
    for _ in range(400):
        x0, y0 = rnd.uniform(0, 150), rnd.uniform(0, 80)
        g = rect(round(x0, 2), round(y0, 2), round(x0 + rnd.uniform(1, 60), 2),
                 round(y0 + rnd.uniform(1, 40), 2))
        corner = rnd.choice([pc.PARK_CORNER_MM, (60.0, 25.0), (0.0, 0.0)])
        assert pc.check_job(g, corner).ok == pi_accepts(g, corner), g


def test_placed_check_agrees_with_pi_make_placement():
    rnd = random.Random(7)
    g = rect(150, 150, 190, 170)
    box = pc.powered_bounds(g)
    for _ in range(300):
        target = (round(rnd.uniform(0, 150), 1), round(rnd.uniform(0, 80), 1))
        anchor = rnd.choice(pc.ANCHORS)
        dx, dy = pc.placement_offset(box, "user", anchor, target)
        pbox = pi_place.Box(box.xmin, box.ymin, box.xmax, box.ymax)
        ax, ay = pi_place.anchor_point(pbox, anchor)
        assert (dx, dy) == (round(target[0] - ax, 3), round(target[1] - ay, 3))
        ok = pc.check_job(g, origin="user", anchor=anchor, target=target,
                          cutting_bounds=(0, 0, 390, 370)).ok
        assert ok == pi_accepts(g, dx=dx, dy=dy), (target, anchor)


def test_default_user_origin_is_refused_with_german_hint():
    g = rect(150, 150, 190, 170)
    res = pc.check_job(g, origin="user", anchor="tr", target=(30.0, 30.0))
    assert not res.ok and res.bounds == pc.Box(30, 30, 70, 50)
    assert res.shift_mm == pytest.approx((48.0, 5.0))
    for part in ("Park-Ecke X0–78 / Y0–35 mm", "Benutzer-Ursprung", "48 mm nach links (X+)",
                 "5 mm nach unten (Y+)", "Ursprung/Bezugspunkt ändern", "X30–70 / Y30–50 mm"):
        assert part in res.message, res.message
    # right of the corner, or below it: accepted (like the Pi)
    assert pc.check_job(g, origin="user", anchor="tr", target=(78.0, 30.0)).ok
    assert pc.check_job(g, origin="user", anchor="tr", target=(30.0, 35.0)).ok
    # anchored with the far corner: the motif lies away from the corner
    assert pc.check_job(g, origin="user", anchor="bl", target=(70.0, 60.0)).ok


def test_absolute_canvas_top_right_strip():
    """Canvas top right = machine X30..78 / Y30..35: inside the work area, refused."""
    res = pc.check_job(rect(40, 31, 60, 50))
    assert not res.ok and "verschieben." in res.message and "Ursprung" not in res.message
    assert pc.check_job(rect(40, 35, 60, 50)).ok
    assert pc.check_job(rect(78, 31, 90, 50)).ok
    assert pc.check_job("G0 X40 Y31\nG1 X50 Y32 S0\n").ok     # never lasers


def test_unknown_origin_and_cutting_bounds():
    g = rect(150, 150, 190, 170)
    assert pc.check_job(g, origin="current", target=None).ok          # Pi decides
    res = pc.check_job(g, origin="user", anchor="tr", target=(360.0, 100.0),
                       cutting_bounds=(0.0, 0.0, 370.0, 360.0))
    assert not res.ok and "außerhalb des Schneidbereichs" in res.message
    assert pc.check_job(g, cutting_bounds=(0.0, 0.0, 370.0, 360.0)).ok


def test_status_parsing():
    from machine.client import MachineStatus
    st = MachineStatus.from_json({"firmware": "marlin", "connected": True,
                                  "park_corner_mm": {"x": 60, "y": 20},
                                  "cutting_bounds": {"x_min": 0, "y_min": 0,
                                                     "x_max": 370, "y_max": 360},
                                  "origin": {"modes": ["absolute", "current", "user"],
                                             "user": [30, 30]},
                                  "position": [100, 50, 5]})
    assert pc.corner_from_status(st) == (60.0, 20.0)
    assert pc.cutting_bounds_from_status(st) == (0.0, 0.0, 370.0, 360.0)
    assert pc.origin_target(st, "user") == (30.0, 30.0)
    assert pc.origin_target(st, "current") == (100.0, 50.0)
    assert pc.origin_target(st, "absolute") is None
    for bad in (None, {}, {"park_corner_mm": {"x": "a", "y": 3}},
                {"park_corner_mm": {"x": -1, "y": 3}}, {"park_corner_mm": [1, 2]}):
        assert pc.corner_from_status(SimpleNamespace(raw=bad)) == pc.PARK_CORNER_MM
    assert pc.cutting_bounds_from_status(SimpleNamespace(raw={"cutting_bounds": {"x_min": 5}})) is None
    # the real Pi status reports both fields
    src = (ROOT / "pi400" / "marlin" / "transport.py").read_text(encoding="utf-8")
    assert '"park_corner_mm": {"x": self.park_corner[0], "y": self.park_corner[1]}' in src
    assert '"cutting_bounds": {"x_min": 0.0, "y_min": 0.0,' in src


class FakePanel:
    def __init__(self, origin="absolute", user=(30.0, 30.0), corner=None):
        self._client = object()
        self.origin = origin
        raw = {} if corner is None else {"park_corner_mm": {"x": corner[0], "y": corner[1]}}
        self._status = SimpleNamespace(raw=raw, coord_convention="origin_top_right",
                                       origin=SimpleNamespace(user=user), position=None)
        self.sent, self.messages = [], []

    def job_origin(self):
        return self.origin, "tr"

    def _show_message(self, text, level):
        self.messages.append((text, level))

    def send_gcode(self, name, gcode, start=False, autorun=False):
        self.sent.append((name, start, autorun))


def test_send_hook_refuses_absolute_motif_in_corner():
    mp = FakePanel()
    reported = []
    pc.attach_park_check(mp, reported.append)
    assert mp.send_gcode("a.gcode", rect(40, 31, 60, 50)) is False
    assert mp.sent == [] and "Nicht gesendet" in reported[0] and "Park-Ecke" in reported[0]
    assert mp.messages and mp.messages[0][0] == reported[0]
    mp.send_gcode("b.gcode", rect(100, 100, 120, 120), start=True)
    assert mp.sent == [("b.gcode", True, False)]


def test_send_hook_uses_reported_corner_and_offline_passes():
    mp = FakePanel(corner=(20.0, 20.0))
    pc.attach_park_check(mp)
    mp.send_gcode("a.gcode", rect(40, 31, 60, 50))
    assert mp.sent == [("a.gcode", False, False)]
    off = FakePanel()
    off._client = None             # not connected: the panel shows its own message
    pc.attach_park_check(off)
    off.send_gcode("a.gcode", rect(40, 31, 60, 50))
    assert off.sent == [("a.gcode", False, False)]


def test_send_hook_placed_origin():
    mp = FakePanel(origin="user")
    reported = []
    pc.attach_park_check(mp, reported.append)
    g = rect(150, 150, 190, 170)
    # one-click autorun at the user origin (30, 30): refused, nothing uploaded
    assert mp.send_gcode("a.gcode", g, autorun=True) is False and mp.sent == []
    assert reported[-1].startswith("Nicht gestartet") and "Benutzer-Ursprung" in reported[-1]
    # plain send: uploaded (origin may still change), with a warning
    mp.send_gcode("a.gcode", g)
    assert mp.sent == [("a.gcode", False, False)] and reported[-1].startswith("Gesendet, aber")
    # start=True runs absolute: no origin warning
    n = len(reported)
    mp.send_gcode("a.gcode", g, start=True)
    assert len(reported) == n
    mp._status.origin.user = (80.0, 30.0)
    assert mp.send_gcode("b.gcode", g, autorun=True) is None and mp.sent[-1] == ("b.gcode", False, True)


def test_history_wrapper_passes_autorun(tmp_path):
    from lumacut_job.history import JobHistory
    from lumacut_job.history_qt import attach_history
    mp = FakePanel()
    attach_history(mp, JobHistory(tmp_path))
    pc.attach_park_check(mp)
    mp.send_gcode("a.gcode", rect(100, 100, 120, 120), autorun=True)
    assert mp.sent == [("a.gcode", False, True)]
    assert [e.name for e in JobHistory(tmp_path).entries()] == ["a.gcode"]
    assert mp.send_gcode("b.gcode", rect(40, 31, 60, 50)) is False
    assert [e.name for e in JobHistory(tmp_path).entries()] == ["a.gcode"]   # refused: not recorded


def test_main_window_estimate_and_send_refuse(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    monkeypatch.setenv("LUMACUT_HISTORY_DIR", str(tmp_path / "hist"))
    main = pytest.importorskip("main")
    from lumacut_canvas.model import Geometry, Shape
    win = main.LumaCutStudio()
    try:
        tools = win.job_tools
        doc = win.canvas.document
        # display top right (0..20 / 0..3 mm) = machine X370..390 – fine; put it
        # at display x 300 → machine X ≈ 70..90, Y 31..33: in the corner
        doc.add_shape(Shape("rect", Geometry(300, 1, 30, 2), doc.active_layer_id))
        g, _ = tools.job_gcode()
        assert not pc.check_job(g).ok
        assert "Park-Ecke" in tools.park_preflight(g)
        tools.show_estimate()
        assert "Park-Ecke" in win.statusBar().currentMessage()
        mp = win.machine_panel
        mp._client = object()
        calls = []
        monkeypatch.setattr(mp, "_run_upload", lambda label, task: calls.append(label) or True)
        assert mp.send_gcode("x.gcode", g) is False and calls == []
        assert "Park-Ecke" in win.statusBar().currentMessage()
        win._send_canvas_job()
        assert calls == [] and "Gesendet" not in win.statusBar().currentMessage()
    finally:
        win.machine_panel._client = None
        win.canvas.undo_stack.setClean()
        win.close()


def test_one_click_start_refuses_park_corner(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from scanprobe.job_flow_qt import install_one_click
    from scanprobe.panel import ScanPanel
    from lumacut_job.qt_tools import JobTools
    ed = CanvasEditor()
    panel = ScanPanel(ed, ask=False)
    mp = FakePanel(origin="absolute")
    mp.client = object()
    mp.set_external_operation = lambda label: None
    g = rect(40, 31, 60, 50)
    tools = SimpleNamespace(job_gcode=lambda: (g, ""), machine=mp)
    tools.park_preflight = lambda gcode: JobTools.park_preflight(tools, gcode)
    win = SimpleNamespace(canvas=ed, scan_panel=panel, machine_panel=mp, job_tools=tools)
    ctrl = install_one_click(win, ask=False, port_factory=lambda c: None)
    try:
        assert not ctrl.start() and "Park-Ecke" in ctrl.last_message and not ctrl.busy
    finally:
        ctrl.shutdown()
        panel.shutdown()
        ed.undo_stack.setClean()
