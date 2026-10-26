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
FAR = (-60.0, 15.0)      # gedachter Versatz: linker Rand > 40 mm außer Reichweite
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import heightmap as pi_hm, transport as pi_tr  # noqa: E402


def pi_reachable(x, y, offset=OFFSET):
    """Echter ``MarlinTransport.probe_reachable`` (kein Port wird geöffnet)."""
    t = pi_tr.MarlinTransport("/dev/null")
    t.probe_xy_offset_mm = offset
    return t.probe_reachable(x, y)


def screen_rect_gcode(x0, y0, w, h):
    """Rechteck in Bildschirm-mm (oben links, x nach rechts) → Maschinen-G-Code."""
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]
    m = [(390.0 - x, 30.0 + y) for x, y in pts]
    lines = ["G90", f"G0 X{m[0][0]:.3f} Y{m[0][1]:.3f}", "M4 S0",
             f"G1 X{m[1][0]:.3f} Y{m[1][1]:.3f} F1500 S500"]
    lines += [f"G1 X{x:.3f} Y{y:.3f}" for x, y in m[2:]] + ["M5"]
    return "\n".join(lines) + "\n"


def pi_grids(gcode, offset=OFFSET):
    return pi_hm.plan_probe(gcode.splitlines(), pi_hm.Box(30, 30, 390, 370),
                            lambda x, y: pi_reachable(x, y, offset))


def pi_points(gcode, offset=OFFSET):
    return sum(sum(g.reachable) for g in pi_grids(gcode, offset))


def pi_substitutes(gcode, offset=OFFSET):
    return sorted((round(x, 6), round(y, 6), round(p[0], 6), round(p[1], 6))
                  for g in pi_grids(gcode, offset)
                  for i, p in enumerate(g.probe_at) if p is not None
                  for x, y in [g.point(i)])


def studio_substitutes(rep):
    return sorted((round(s.x, 6), round(s.y, 6), round(s.probe_x, 6), round(s.probe_y, 6))
                  for s in rep.substitutes)


def test_reach_constants_match_pi_source():
    tr = (ROOT / "pi400" / "marlin" / "transport.py").read_text(encoding="utf-8")
    assert "return self._probe_head_ok(x - dx, y - dy)" in tr
    assert pi_tr.PROBE_HEAD_MIN == reach.PROBE_HEAD_MIN
    assert pi_tr.PROBE_HEAD_MAX == reach.PROBE_HEAD_MAX
    for name in ("CELL_MM", "REGION_GAP_MM", "REGION_MARGIN_MM", "GRID_INSET_MM",
                 "GRID_SPACING_MM", "MAX_PER_SIDE", "MAX_REGIONS", "MAX_TOTAL_POINTS",
                 "SUBSTITUTE_MAX_MM", "SUBSTITUTE_STEP_MM"):
        assert getattr(pi_hm, name) == getattr(reach, name), name
    assert "{ 0, 0, 0 }" in (ROOT / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")


def test_nearest_reachable_matches_pi():
    rnd = random.Random(7)
    for _ in range(30):
        x, y = rnd.uniform(30, 390), rnd.uniform(30, 370)
        for off in (OFFSET, FAR):
            fn = lambda px, py, o=off: pi_reachable(px, py, o)
            assert reach.nearest_reachable(x, y, reach.pi_reachable(off)) == \
                pi_hm.nearest_reachable(x, y, fn)


def test_reach_region_default_offset():
    w = reach.work_reach(OFFSET)
    assert (w.xmin, w.ymin, w.xmax, w.ymax) == (30, 30, 357, 370)
    s = reach.screen_box(w)
    assert (s.xmin, s.ymin, s.xmax, s.ymax) == (33, 0, 360, 340)
    lr = reach.laser_reach(OFFSET)
    assert (lr.xmin, lr.ymin, lr.xmax, lr.ymax) == (-13, 25, 357, 375)


def test_bottom_left_design_is_substituted_on_pi_and_in_studio():
    """Linker 33-mm-Streifen: Pi (b966c89) misst daneben, kein Abbruch mehr."""
    g = screen_rect_gcode(5, 300, 20, 30)          # unten links, 20 mm breit
    rep = reach.check_gcode(g, OFFSET)
    assert not rep.ok and not rep.none_reachable and rep.fallback_point is None
    assert rep.reachable_points == rep.total_points == pi_points(g)
    assert studio_substitutes(rep) == pi_substitutes(g)
    assert all(s.probe_x == 357 and s.distance_mm <= 40 for s in rep.substitutes)
    assert rep.warning.startswith("Achtung:") and "am linken Rand (Maschine X > 357)" in rep.warning
    assert "neben dem Werkstück" in rep.warning and "Gelasert wird trotzdem" in rep.warning


def test_left_edge_beyond_40mm_is_truly_unreachable_on_pi_and_in_studio():
    g = screen_rect_gcode(2, 150, 10, 10)          # Maschine X378–388, Reichweite X ≤ 320
    with pytest.raises(ValueError, match="Kein Abtastpunkt erreichbar"):
        pi_points(g, FAR)
    rep = reach.check_gcode(g, FAR)
    assert not rep.ok and rep.reachable_points == 0 and rep.none_reachable
    assert rep.shift_x < 0 and rep.shift_y == 0
    assert "zu weit links" in rep.message and "nach rechts" in rep.message
    assert "X30–320" in rep.message
    fx, fy = rep.fallback_point
    assert fx == 320 and 180 <= fy <= 190
    assert pi_reachable(fx, fy, FAR)                # der Pi nimmt den Ersatzpunkt an
    assert "linken Rand" in rep.warning and "Gelasert wird trotzdem" in rep.warning
    # Um die empfohlenen mm nach rechts geschoben → Pi findet einen Punkt
    mm = int(rep.message.split("mind. ")[1].split(" mm")[0])
    moved = screen_rect_gcode(2 + mm, 150, 10, 10)
    assert pi_points(moved, FAR) >= 1
    assert reach.check_gcode(moved, FAR).ok


def test_bottom_left_wide_design_is_reachable_with_partial_warning():
    g = screen_rect_gcode(0, 280, 80, 60)          # reicht über die 33-mm-Kante
    rep = reach.check_gcode(g, OFFSET)
    assert pi_points(g) >= 1 and not rep.none_reachable and rep.fallback_point is None
    assert rep.substitutes and "linken Rand" in rep.warning


def test_top_strip_is_directly_reachable_now():
    """Kopf darf bis Y10 (b966c89): oberer Rand braucht keinen Ersatzpunkt mehr."""
    g = screen_rect_gcode(150, 1, 30, 8)
    rep = reach.check_gcode(g, OFFSET)
    assert rep.ok and rep.warning == "" and rep.reachable_points == pi_points(g) >= 1
    assert pi_substitutes(g) == []


def test_bottom_right_corner_is_reachable():
    rep = reach.check_gcode(screen_rect_gcode(330, 320, 25, 18), OFFSET)
    assert rep.ok and rep.warning == "" and rep.fallback_point is None


def test_substitute_sides_and_distance():
    box = reach.work_reach(OFFSET)
    sb = reach.substitute(370, 40, box)
    assert sb.sides == ("links",) and (sb.probe_x, sb.probe_y) == (357, 40)
    assert abs(sb.distance_mm - 13) < 1e-9
    assert reach.substitute(200, 200, box) is None
    corner = reach.Substitute(370, 20, 357, 25)
    assert corner.sides == ("links", "oben")
    w = reach.substitution_warning([corner], reach.laser_reach(OFFSET))
    assert "1 Abtastpunkt am linken Rand" in w and "oberen/hinteren Rand (Maschine Y < 25)" in w
    assert "14 mm" in w


@pytest.mark.parametrize("seed", range(40))
def test_studio_counts_same_points_as_pi(seed):
    rnd = random.Random(seed)
    parts = []
    for _ in range(rnd.randint(1, 3)):
        w, h = rnd.uniform(3, 150), rnd.uniform(3, 120)
        parts.append(screen_rect_gcode(rnd.uniform(0, 360 - w), rnd.uniform(0, 340 - h), w, h))
    g = "".join(parts)
    for off in (OFFSET, FAR):
        rep = reach.check_gcode(g, off)
        try:
            n, subs = pi_points(g, off), pi_substitutes(g, off)
        except ValueError:
            n, subs = 0, []
        assert rep.reachable_points == n
        if n:
            assert studio_substitutes(rep) == subs


def test_explain_pi_error():
    g = screen_rect_gcode(2, 150, 10, 10)
    pi_text = ("Kein Abtastpunkt erreichbar: der Taster kommt an keine Stelle des Motivs – "
               "Motiv weiter in die Mitte schieben, dann neu starten.")
    assert "nach rechts" in reach.explain_pi_error(pi_text, g, FAR)
    general = reach.explain_pi_error(pi_text, None, OFFSET)
    assert "x 33–360" in general and "y 0–340" in general and "nach" not in general
    assert reach.explain_pi_error("anderer Fehler", g) == "anderer Fehler"


def test_pi_offset_from_status():
    st = type("S", (), {"raw": {"probe_xy_offset_mm": [-20, 10]}})()
    assert reach.pi_offset(st) == (-20.0, 10.0)
    assert reach.pi_offset(object()) == reach.PROBE_OFFSET_MM


class PointPort(PiAutorunPort):
    """Pi-Port, der ``autorun`` mit x/y annimmt und wie der Pi ohne Punkt ablehnt."""

    def __init__(self, *a, pi_refuses=True, offset=None, **kw):
        super().__init__(*a, **kw)
        self.points = []
        self.pi_refuses = pi_refuses
        self.offset = offset

    def status(self):
        st = super().status()
        if self.offset is not None:
            st.raw["probe_xy_offset_mm"] = list(self.offset)
        return st

    def autorun(self, name, x=None, y=None):
        self.points.append(None if x is None else (x, y))
        if x is None and self.pi_refuses:
            raise RuntimeError("HTTP 400: Kein Abtastpunkt erreichbar: der Taster kommt an "
                               "keine Stelle des Motivs")
        return super().autorun(name)


def test_one_click_warns_and_pi_substitutes_itself():
    """Linker Streifen: der Pi misst selbst daneben (b966c89), Studio warnt vorab."""
    hw = adapters.simulated_setup()
    port = PointPort(hw.machine, pi_refuses=False)
    events = []
    flow = OneClickJob(port, None, poll_s=0.0, sleep=lambda s: None, on_event=events.append)
    res = flow.run(screen_rect_gcode(5, 300, 20, 30), "rand.gcode")
    assert res.ok, res.error
    assert port.points == [None]                          # normales autorun, kein x/y
    assert any(n.startswith("Achtung") and "linken Rand" in n for n in res.notes)
    assert any(e.get("warning") for e in events)


def test_one_click_beyond_40mm_lasers_with_fallback_point():
    hw = adapters.simulated_setup()
    port = PointPort(hw.machine, offset=FAR)
    events = []
    flow = OneClickJob(port, None, poll_s=0.0, sleep=lambda s: None, on_event=events.append)
    res = flow.run(screen_rect_gcode(2, 150, 10, 10), "rand.gcode")
    assert res.ok, res.error
    assert port.points and port.points[0][0] == 320      # gleich mit Ersatzpunkt
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
    assert "40 mm daneben" in res.error


def test_studio_probe_plan_respects_pi_head_limits():
    # Kopf X/Y 10…380/360 wie transport.PROBE_HEAD_MIN/MAX (b966c89)
    t = pi_tr.MarlinTransport("/dev/null")
    for x, y in ((100, 25), (100, 10), (10, 100), (100, 9.9), (9.9, 100), (385, 100),
                 (380, 360), (100, 361)):
        assert DEFAULT_LIMITS.probe_head_ok(x, y) == t._probe_head_ok(x, y), (x, y)
    assert DEFAULT_LIMITS.probe_head_ok(100, 25) and not DEFAULT_LIMITS.probe_head_ok(385, 100)
    r = DEFAULT_LIMITS.probe_laser_rect(OFFSET)
    assert (r.xmin, r.ymin, r.xmax, r.ymax) == (30, 30, 357, 370)


def test_studio_probe_plan_substitutes_unreachable_points():
    area = ProbeArea("a", Polygon([(360, 100), (385, 100), (385, 160), (360, 160)]))
    job = plan_probe_job([area])
    pts = job.points
    assert pts and all(p.substituted and p.probe_x == 357 for p in pts)
    for p in pts:
        assert DEFAULT_LIMITS.probe_head_ok(p.probe_x - OFFSET[0], p.probe_y - OFFSET[1])
        assert p.x - p.probe_x <= 40
    assert any(w.startswith("Achtung") and "linken Rand" in w for w in job.warnings)
    # oberer Rand ist jetzt direkt erreichbar
    top = plan_probe_job([ProbeArea("t", Polygon([(100, 31), (160, 31), (160, 44), (100, 44)]))])
    assert top.points and not any(p.substituted for p in top.points)


def test_studio_probe_plan_skips_points_beyond_40mm():
    from scanprobe.probe_plan import ProbeSettings
    area = ProbeArea("a", Polygon([(370, 100), (388, 100), (388, 160), (370, 160)]))
    job = plan_probe_job([area], ProbeSettings(probe_offset_mm=FAR))
    assert not job.points
    assert any("kein abtastbarer Punkt" in w for w in job.warnings)


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
