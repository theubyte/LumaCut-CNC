"""Erreichbarkeit des Tasters: Studio rechnet wie der Pi (Anforderungen 2026-10-26 §2.4)."""
from __future__ import annotations

import importlib.util
import pathlib
import random
import sys

import pytest

from scanprobe import adapters, reach
from scanprobe.geometry import DEFAULT_LIMITS, Polygon
from scanprobe.job_flow import OneClickJob
from scanprobe.probe_plan import ProbeArea, plan_probe_job

from test_job_flow import PiAutorunPort

ROOT = pathlib.Path(__file__).resolve().parents[3]
OFFSET = (-23.0, 15.0)   # docs/MASCHINE.md, Stand 25.10.2026


def _pi_heightmap():
    spec = importlib.util.spec_from_file_location(
        "pi_heightmap", ROOT / "pi400" / "marlin" / "heightmap.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pi_heightmap"] = mod
    spec.loader.exec_module(mod)
    return mod


def pi_reachable(x, y, offset=OFFSET):
    """``transport.probe_reachable`` mit ``safe_zone_xy_mm`` 30 und PROBE_HEAD_MAX 380/360."""
    hx, hy = x - offset[0], y - offset[1]
    return 30.0 <= hx <= 380.0 and 30.0 <= hy <= 360.0


def screen_rect_gcode(x0, y0, w, h):
    """Rechteck in Bildschirm-mm (oben links, x nach rechts) → Maschinen-G-Code."""
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]
    m = [(390.0 - x, 30.0 + y) for x, y in pts]
    lines = ["G90", f"G0 X{m[0][0]:.3f} Y{m[0][1]:.3f}", "M4 S0",
             f"G1 X{m[1][0]:.3f} Y{m[1][1]:.3f} F1500 S500"]
    lines += [f"G1 X{x:.3f} Y{y:.3f}" for x, y in m[2:]] + ["M5"]
    return "\n".join(lines) + "\n"


def pi_points(gcode):
    hm = _pi_heightmap()
    grids = hm.plan_probe(gcode.splitlines(), hm.Box(30, 30, 390, 370), pi_reachable)
    return sum(sum(g.reachable) for g in grids)


def test_reach_constants_match_pi_source():
    tr = (ROOT / "pi400" / "marlin" / "transport.py").read_text(encoding="utf-8")
    assert "PROBE_HEAD_MAX = (380.0, 360.0)" in tr
    assert "return self._probe_head_ok(x - dx, y - dy)" in tr
    hm = _pi_heightmap()
    for name in ("CELL_MM", "REGION_GAP_MM", "REGION_MARGIN_MM", "GRID_INSET_MM",
                 "GRID_SPACING_MM", "MAX_PER_SIDE", "MAX_REGIONS", "MAX_TOTAL_POINTS"):
        assert getattr(hm, name) == getattr(reach, name), name
    assert "{ 0, 0, 0 }" in (ROOT / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")


def test_reach_region_default_offset():
    w = reach.work_reach(OFFSET)
    assert (w.xmin, w.ymin, w.xmax, w.ymax) == (30, 45, 357, 370)
    s = reach.screen_box(w)
    assert (s.xmin, s.ymin, s.xmax, s.ymax) == (33, 15, 360, 340)


def test_bottom_left_design_is_truly_unreachable_on_pi_and_in_studio():
    g = screen_rect_gcode(5, 300, 20, 30)          # unten links, 20 mm breit
    with pytest.raises(ValueError, match="Kein Abtastpunkt erreichbar"):
        pi_points(g)
    rep = reach.check_gcode(g, OFFSET)
    assert not rep.ok and rep.reachable_points == 0 and rep.none_reachable
    assert rep.shift_x < 0 and rep.shift_y == 0
    assert "zu weit links" in rep.message and "nach rechts" in rep.message
    assert "x 33–360" in rep.message and "X30–357" in rep.message
    # Neue Regel (§2.4): Warnung + Ersatzpunkt statt Abbruch
    assert rep.warning.startswith("Achtung:") and "am linken Rand (Maschine X > 357)" in rep.warning
    assert "neben dem Werkstück" in rep.warning and "Gelasert wird trotzdem" in rep.warning
    fx, fy = rep.fallback_point
    assert fx == 357 and 330 <= fy <= 360
    assert pi_reachable(fx, fy)                     # der Pi nimmt den Ersatzpunkt an
    # Um die empfohlenen mm nach rechts geschoben → Pi findet einen Punkt
    mm = int(rep.message.split("mind. ")[1].split(" mm")[0])
    assert pi_points(screen_rect_gcode(5 + mm, 300, 20, 30)) >= 1
    assert not reach.check_gcode(screen_rect_gcode(5 + mm, 300, 20, 30), OFFSET).none_reachable


def test_bottom_left_wide_design_is_reachable_with_partial_warning():
    g = screen_rect_gcode(0, 280, 80, 60)          # reicht über die 33-mm-Kante
    rep = reach.check_gcode(g, OFFSET)
    assert pi_points(g) >= 1 and not rep.none_reachable and rep.fallback_point is None
    assert rep.substitutes and "linken Rand" in rep.warning


def test_top_strip_warns_upper_edge():
    g = screen_rect_gcode(150, 1, 30, 8)
    with pytest.raises(ValueError):
        pi_points(g)
    rep = reach.check_gcode(g, OFFSET)
    assert rep.none_reachable and rep.shift_y > 0 and "nach unten" in rep.message
    assert "oberen/hinteren Rand (Maschine Y < 45)" in rep.warning
    assert rep.fallback_point[1] == 45


def test_bottom_right_corner_is_reachable():
    rep = reach.check_gcode(screen_rect_gcode(330, 320, 25, 18), OFFSET)
    assert rep.ok and rep.warning == "" and rep.fallback_point is None


def test_substitute_sides_and_distance():
    box = reach.work_reach(OFFSET)
    sb = reach.substitute(370, 40, box)
    assert sb.sides == ("links", "oben") and (sb.probe_x, sb.probe_y) == (357, 45)
    assert abs(sb.distance_mm - (13 ** 2 + 5 ** 2) ** 0.5) < 1e-9
    assert reach.substitute(200, 200, box) is None
    w = reach.substitution_warning([sb], box)
    assert "1 Abtastpunkt am linken Rand" in w and "oberen/hinteren Rand" in w and "14 mm" in w


@pytest.mark.parametrize("seed", range(40))
def test_studio_counts_same_points_as_pi(seed):
    rnd = random.Random(seed)
    parts = []
    for _ in range(rnd.randint(1, 3)):
        w, h = rnd.uniform(3, 150), rnd.uniform(3, 120)
        parts.append(screen_rect_gcode(rnd.uniform(0, 360 - w), rnd.uniform(0, 340 - h), w, h))
    g = "".join(parts)
    rep = reach.check_gcode(g, OFFSET)
    try:
        n = pi_points(g)
    except ValueError:
        n = 0
    assert rep.reachable_points == n


def test_explain_pi_error():
    g = screen_rect_gcode(5, 300, 20, 30)
    pi_text = ("Kein Abtastpunkt erreichbar: der Taster kommt an keine Stelle des Motivs – "
               "Motiv weiter in die Mitte schieben, dann neu starten.")
    assert "nach rechts" in reach.explain_pi_error(pi_text, g, OFFSET)
    general = reach.explain_pi_error(pi_text, None, OFFSET)
    assert "x 33–360" in general and "nach" not in general
    assert reach.explain_pi_error("anderer Fehler", g) == "anderer Fehler"


def test_pi_offset_from_status():
    st = type("S", (), {"raw": {"probe_xy_offset_mm": [-20, 10]}})()
    assert reach.pi_offset(st) == (-20.0, 10.0)
    assert reach.pi_offset(object()) == reach.PROBE_OFFSET_MM


class PointPort(PiAutorunPort):
    """Pi-Port, der ``autorun`` mit x/y annimmt und wie der Pi ohne Punkt ablehnt."""

    def __init__(self, *a, pi_refuses=True, **kw):
        super().__init__(*a, **kw)
        self.points = []
        self.pi_refuses = pi_refuses

    def autorun(self, name, x=None, y=None):
        self.points.append(None if x is None else (x, y))
        if x is None and self.pi_refuses:
            raise RuntimeError("HTTP 400: Kein Abtastpunkt erreichbar: der Taster kommt an "
                               "keine Stelle des Motivs")
        return super().autorun(name)


def test_one_click_warns_and_lasers_with_substitute_point():
    hw = adapters.simulated_setup()
    port = PointPort(hw.machine)
    events = []
    flow = OneClickJob(port, None, poll_s=0.0, sleep=lambda s: None, on_event=events.append)
    res = flow.run(screen_rect_gcode(5, 300, 20, 30), "rand.gcode")
    assert res.ok, res.error
    assert port.points and port.points[0][0] == 357      # gleich mit Ersatzpunkt
    assert any(n.startswith("Achtung") and "linken Rand" in n for n in res.notes)
    assert any(e.get("warning") for e in events)


def test_one_click_pi_refuses_then_retries_with_nearest_point():
    """Pi rechnet anders (z. B. anderer Versatz): 400 → einmal mit Ersatzpunkt."""
    hw = adapters.simulated_setup()
    port = PointPort(hw.machine)
    flow = OneClickJob(port, None, poll_s=0.0, sleep=lambda s: None)
    res = flow.run(screen_rect_gcode(100, 100, 40, 40), "mitte.gcode")
    assert res.ok, res.error
    assert port.points[0] is None and port.points[1] is not None
    assert any("stattdessen einmal bei" in n for n in res.notes)


def test_one_click_reachable_job_has_no_warning():
    hw = adapters.simulated_setup()
    port = PointPort(hw.machine, pi_refuses=False)
    res = OneClickJob(port, None, poll_s=0.0, sleep=lambda s: None).run(
        screen_rect_gcode(100, 100, 40, 40), "mitte.gcode")
    assert res.ok and port.points == [None]
    assert not any(n.startswith("Achtung") for n in res.notes)


def test_one_click_placed_pi_400_is_explained():
    hw = adapters.simulated_setup()
    port = PiAutorunPort(hw.machine)

    class Placed:
        placed = True

        def __getattr__(self, item):
            return getattr(port, item)

        def autorun(self, name):
            raise RuntimeError("HTTP 400: Kein Abtastpunkt erreichbar: der Taster kommt an "
                               "keine Stelle des Motivs")

    flow = OneClickJob(Placed(), None, poll_s=0.0, sleep=lambda s: None, use_pi_mesh=True)
    res = flow.run(screen_rect_gcode(5, 300, 20, 30), "rand.gcode")
    assert res.error_code == "unreachable"
    assert "Abtastbar ist auf dem Bildschirm x 33–360" in res.error
    assert "Ersatzpunkt-Regel" in res.error


def test_studio_probe_plan_respects_pi_head_limits():
    # Kopf darf nicht unter Y30 (Safezone) / über X380
    assert not DEFAULT_LIMITS.probe_head_ok(100, 25)
    assert not DEFAULT_LIMITS.probe_head_ok(385, 100)
    assert DEFAULT_LIMITS.probe_head_ok(380, 360)
    r = DEFAULT_LIMITS.probe_laser_rect(OFFSET)
    assert (r.xmin, r.ymin, r.xmax, r.ymax) == (30, 45, 357, 370)


def test_studio_probe_plan_substitutes_unreachable_points():
    area = ProbeArea("a", Polygon([(100, 31), (160, 31), (160, 44), (100, 44)]))
    job = plan_probe_job([area])
    pts = job.points
    assert pts and all(p.substituted and p.probe_y == 45 for p in pts)
    for p in pts:
        assert DEFAULT_LIMITS.probe_head_ok(p.probe_x - OFFSET[0], p.probe_y - OFFSET[1])
    assert any(w.startswith("Achtung") and "oberen/hinteren Rand" in w for w in job.warnings)


def test_probe_runner_marks_substituted_points():
    from scanprobe.heightmap import SUBSTITUTED, STATUS_NAMES
    from scanprobe.heatmap import heatmap_rgba, SUBSTITUTED_RGBA
    from scanprobe.probing import ProbeRunner
    from scanprobe.geometry import Rect

    class FlatProbe:
        def __init__(self):
            self.at = []

        def probe_z(self, x, y, safe_z, feed, max_depth):
            self.at.append((x, y))
            return 3.0

    area = ProbeArea("a", Polygon([(330, 100), (380, 100), (380, 160), (330, 160)]))
    job = plan_probe_job([area])
    probe = FlatProbe()
    res = ProbeRunner(probe).run(job)
    assert res.ok and res.substituted
    assert all(x <= 357 + 1e-9 for x, _ in probe.at)       # nie außerhalb der Reichweite
    hm = res.maps.maps[0]
    st = hm.stats()
    assert st["substituted"] > 0 and STATUS_NAMES[SUBSTITUTED] == "substituted"
    assert (hm.status == SUBSTITUTED).any() and hm.measured_count == hm.status.size - int(
        (hm.status == 0).sum())
    assert any(w.startswith("Achtung") for w in res.warnings)
    rgba, _, _ = heatmap_rgba(res.maps, Rect(30, 30, 390, 370), 2.0)
    assert (rgba.reshape(-1, 4) == SUBSTITUTED_RGBA).all(axis=1).any()
    # Rundreise über JSON behält die Markierung
    from scanprobe.heightmap import HeightMap
    assert (HeightMap.from_dict(hm.to_dict()).status == SUBSTITUTED).any()
