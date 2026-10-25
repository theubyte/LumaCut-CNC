"""Tests für scanprobe: Kachel-Scan, Stitching, Objekterkennung, Mehrbereichs-Proben,
Höhenmeshes, Fokuskorrektur, Wiederverwendung, Pause/Abbruch – alles mit Fakes."""
from __future__ import annotations

import json
import math
import threading

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from scanprobe import (  # noqa: E402
    CameraCalibration, Cancelled, FocusSettings, HeightMap, HeightMapSet, Mosaic, Polygon,
    ProbeArea, ProbeRunner, ProbeSettings, Progress, Rect, RunControl, ScanProbeWorkflow,
    TileScanner, apply_focus_compensation, areas_from_design_bounds, areas_from_objects,
    detect_objects, plan_probe_job, plan_tiles, render_heatmap, stitch_mosaic,
)
from scanprobe.fakes import FakeCamera, FakeMachine, SyntheticBed  # noqa: E402
from scanprobe.geometry import circle_polygon, DEFAULT_LIMITS  # noqa: E402
from scanprobe.heightmap import MEASURED, INTERPOLATED, FAILED  # noqa: E402

RECT = (60, 60, 160, 140)
CIRCLE = ((260, 240), 50)


def tilt(x, y):
    return 3.0 + 0.01 * (x - 60) + 0.005 * (y - 60)


def dome(x, y):
    return 4.0 + 0.6 * math.exp(-((x - 260) ** 2 + (y - 240) ** 2) / (2 * 20 ** 2))


@pytest.fixture(scope="module")
def bed():
    return SyntheticBed.with_objects(objects=[
        {"kind": "rect", "rect": RECT, "z": tilt},
        {"kind": "circle", "center": CIRCLE[0], "r": CIRCLE[1], "z": dome},
    ])


@pytest.fixture(scope="module")
def cal():
    return CameraCalibration(640, 480, px_per_mm=4.0, scan_z=40, offset_mm=(30, -20), rotation_deg=1.5)


@pytest.fixture(scope="module")
def scanned(bed, cal):
    m = FakeMachine(bed, position_error_mm=0.4, seed=3)
    cam = FakeCamera(m, bed, cal)
    b = Rect(30, 30, 390, 370)
    plan = plan_tiles(b, cal, 0.25)
    tiles = TileScanner(m, cam, cal, settle_s=0).run(plan)
    return m, plan, tiles, stitch_mosaic(tiles, cal, b, mm_per_px=0.25)


# ---------------------------------------------------------------- Kalibrierung
def test_calibration_roundtrip_and_pixel_mapping(tmp_path, cal):
    u, v = 100.0, 300.0
    x, y = cal.pixel_to_machine(u, v, (100, 120))
    assert cal.machine_to_pixel(x, y, (100, 120)) == pytest.approx((u, v), abs=1e-6)
    hx, hy = cal.head_for_view_center(200, 200)
    cx, cy = cal.pixel_to_machine((cal.image_width - 1) / 2, (cal.image_height - 1) / 2, (hx, hy))
    assert (cx, cy) == pytest.approx((200, 200), abs=1e-6)
    p = tmp_path / "cam.json"
    cal.save(p)
    assert CameraCalibration.load(p).to_dict() == cal.to_dict()


def test_undistort_removes_lens_distortion(bed):
    k = [[700, 0, 319.5], [0, 700, 239.5], [0, 0, 1]]
    cal = CameraCalibration(640, 480, px_per_mm=4.0, offset_mm=(0, 0), camera_matrix=k,
                            dist_coeffs=[-0.25, 0.08, 0, 0, 0])
    m = FakeMachine(bed)
    m.move_to(120, 110)
    ref = FakeCamera(m, bed, cal).capture()
    raw = FakeCamera(m, bed, cal, distort=True).capture()
    und = cal.undistort(raw)
    c = (slice(40, -40), slice(40, -40))
    err_raw = np.abs(raw[c].astype(float) - ref[c]).mean()
    err_und = np.abs(und[c].astype(float) - ref[c]).mean()
    assert err_und < err_raw * 0.6


# ---------------------------------------------------------------- Kacheln + Mosaik
def test_tile_plan_is_serpentine_with_overlap(cal):
    plan = plan_tiles(Rect(30, 30, 390, 370), cal, 0.25)
    fw, fh = cal.usable_fov_mm
    assert plan.rows * plan.cols == len(plan.tiles) > 1
    rows = [[t for t in plan.tiles if t.row == r] for r in range(plan.rows)]
    assert [t.col for t in rows[0]] == sorted(t.col for t in rows[0])
    assert [t.col for t in rows[1]] == sorted((t.col for t in rows[1]), reverse=True)
    xs = sorted({round(t.view_center[0], 3) for t in plan.tiles})
    assert max(np.diff(xs)) <= fw * 0.75 + 1e-6
    assert plan.estimate_seconds() > 0
    for t in plan.tiles:
        assert DEFAULT_LIMITS.reachable(*t.head)


def test_scanner_moves_z_first_then_xy(scanned, cal):
    m, plan, tiles, _ = scanned
    assert len(tiles) == len(plan.tiles)
    first = m.moves[0]
    assert first[2] == cal.scan_z and (first[0], first[1]) == (0.0, 0.0)


def test_stitched_mosaic_is_accurate_and_refinement_helps(bed, cal, scanned):
    _, _, tiles, mos = scanned
    s = 0.25
    gt = bed.image[int(30 / s):int(370 / s), int(30 / s):int(390 / s)]
    g = cv2.cvtColor(gt, cv2.COLOR_BGR2GRAY).astype(float)

    def err(mo):
        a = cv2.cvtColor(mo.image, cv2.COLOR_BGR2GRAY).astype(float)
        return np.abs(g - a)[mo.coverage].mean()

    plain = stitch_mosaic(tiles, cal, Rect(30, 30, 390, 370), mm_per_px=0.25, refine=False)
    assert mos.coverage.mean() > 0.97
    assert err(mos) < err(plain)
    assert err(mos) < 3.0
    x, y = mos.pixel_to_machine(*mos.machine_to_pixel(123.4, 234.5))
    assert (x, y) == pytest.approx((123.4, 234.5), abs=1e-6)


def test_mosaic_save_load(tmp_path, scanned):
    mos = scanned[3]
    mos.save(tmp_path / "scan.png")
    meta = json.loads((tmp_path / "scan.json").read_text())
    assert meta["mm_per_px"] == pytest.approx(0.25)
    back = Mosaic.load(tmp_path / "scan.png")
    assert back.image.shape == mos.image.shape and back.origin_mm == pytest.approx(mos.origin_mm)


# ---------------------------------------------------------------- Erkennung
def test_detects_rectangle_and_circle(scanned):
    objs = detect_objects(scanned[3])
    kinds = sorted(o.kind for o in objs)
    assert kinds == ["circle", "rectangle"]
    r = next(o for o in objs if o.kind == "rectangle")
    assert r.bounds.to_list() == pytest.approx(list(RECT), abs=1.5)
    c = next(o for o in objs if o.kind == "circle")
    assert c.radius_mm == pytest.approx(50, abs=1.5)
    assert c.center == pytest.approx(CIRCLE[0], abs=1.5)


# ---------------------------------------------------------------- Probenplanung
def test_areas_from_design_bounds_only_probes_used_objects(scanned):
    objs = detect_objects(scanned[3])
    areas, notes = areas_from_design_bounds([Rect(80, 80, 120, 120)], objs)
    assert len(areas) == 1 and areas[0].kind == "rectangle"
    areas2, notes2 = areas_from_design_bounds([Rect(300, 20, 340, 50)], objs)
    assert len(areas2) == 1 and areas2[0].source == "design"
    assert notes2


def test_probe_plan_inside_area_reachable_and_short(scanned):
    objs = detect_objects(scanned[3])
    s = ProbeSettings(spacing_mm=12)
    job = plan_probe_job(areas_from_objects(objs), s)
    assert job.points
    areas = {a.id: a for a in areas_from_objects(objs)}
    for p in job.points:
        assert areas[p.area_id].polygon.contains_with_margin(p.x, p.y, s.margin_mm - 1e-6)
        assert DEFAULT_LIMITS.reachable(p.x + s.probe_offset_mm[0], p.y + s.probe_offset_mm[1])
    # Bereiche zusammenhängend (nicht hin und her springen)
    seq = [p.area_id for p in job.points]
    assert sum(a != b for a, b in zip(seq, seq[1:])) == len(set(seq)) - 1
    rnd = list(job.points)
    np.random.default_rng(0).shuffle(rnd)
    from scanprobe.geometry import path_length
    assert job.travel_mm() < path_length([(p.x, p.y) for p in rnd], (0, 0)) * 0.5
    assert job.estimate_seconds() > 0


def test_polygon_area_grid_respects_shape():
    poly = Polygon([(100, 100), (200, 100), (100, 200)])
    job = plan_probe_job([ProbeArea("tri", poly, "polygon")], ProbeSettings(spacing_mm=10))
    assert all(poly.contains(p.x, p.y) for p in job.points)
    assert len(job.points) > 10


# ---------------------------------------------------------------- Proben
def _probe(bed, areas, settings=None, **machine_kw):
    m = FakeMachine(bed, **machine_kw)
    job = plan_probe_job(areas, settings or ProbeSettings(spacing_mm=12, adaptive=False))
    return m, job, ProbeRunner(m).run(job)


def _areas():
    return [ProbeArea.from_rect("rect", Rect(*RECT)),
            ProbeArea("circle", circle_polygon(*CIRCLE[0], CIRCLE[1]), "circle")]


def test_probing_builds_one_map_per_area_with_accurate_heights(bed):
    _, _, res = _probe(bed, _areas())
    assert res.ok and len(res.maps.maps) == 2
    for x, y in [(70, 70), (110, 100), (150, 130)]:
        assert res.maps.surface_z(x, y) == pytest.approx(tilt(x, y), abs=0.02)
    assert res.maps.surface_z(260, 240, "bilinear") == pytest.approx(dome(260, 240), abs=0.15)
    st = res.maps.get("rect").stats()
    assert st["tilt_mm_per_100mm"][0] == pytest.approx(1.0, abs=0.05)
    assert res.maps.surface_z(10, 10) is None  # außerhalb aller Bereiche


def test_failed_points_are_retried_then_interpolated(bed):
    s = ProbeSettings(spacing_mm=12, adaptive=False, retries=1)
    job = plan_probe_job([ProbeArea.from_rect("rect", Rect(*RECT))], s)
    bad = job.points[len(job.points) // 2]
    m = FakeMachine(bed)
    always = set()
    # Fehler am Punkt und an allen Wiederholpositionen
    orig = m.probe_z

    def flaky(x, y, **kw):
        if math.hypot(x - bad.x, y - bad.y) < 2.5:
            always.add((x, y))
            return None
        return orig(x, y, **kw)

    m.probe_z = flaky
    res = ProbeRunner(m).run(job)
    hm = res.maps.get("rect")
    assert hm.status[bad.j, bad.i] in (FAILED, INTERPOLATED)
    assert len(always) == 1 + s.retries
    assert res.failures and res.failures[0][0] == "rect"
    assert hm.z_at(bad.x, bad.y) == pytest.approx(tilt(bad.x, bad.y), abs=0.05)


def test_random_failures_recovered_by_retry(bed):
    _, _, res = _probe(bed, _areas(), ProbeSettings(spacing_mm=12, adaptive=False, retries=3),
                       probe_fail_rate=0.2, seed=5)
    assert res.ok
    assert any("Wiederholung" in l or "retry" in l.lower() for l in res.log) or res.probes > 0


def test_outlier_is_remeasured(bed):
    s = ProbeSettings(spacing_mm=12, adaptive=False)
    job = plan_probe_job([ProbeArea.from_rect("rect", Rect(*RECT))], s)
    target = job.points[len(job.points) // 2]
    m = FakeMachine(bed)
    orig = m.probe_z
    hits = {"n": 0}

    def spiky(x, y, **kw):
        z = orig(x, y, **kw)
        if (x, y) == (target.x, target.y) and hits["n"] == 0:
            hits["n"] += 1
            return z + 2.0  # Span unter dem Taster
        return z

    m.probe_z = spiky
    res = ProbeRunner(m).run(job)
    assert res.outliers
    assert res.maps.surface_z(target.x, target.y) == pytest.approx(tilt(target.x, target.y), abs=0.05)


def test_adaptive_refinement_adds_points_on_curved_surface():
    def bump(x, y):
        return 4.0 + 0.6 * math.exp(-((x - 260) ** 2 + (y - 240) ** 2) / (2 * 15 ** 2))

    curved = SyntheticBed.with_objects(objects=[{"kind": "rect", "rect": (200, 180, 320, 300), "z": bump}])
    area = [ProbeArea.from_rect("r", Rect(200, 180, 320, 300))]
    _, _, flat = _probe(curved, area, ProbeSettings(spacing_mm=25, adaptive=False))
    _, _, ada = _probe(curved, area, ProbeSettings(spacing_mm=25, adaptive=True, adaptive_threshold_mm=0.02))
    assert ada.adaptive_points > 0 and any("verfeinert" in l for l in ada.log)

    def rms(r):
        pts = [(260 + dx, 240 + dy) for dx in range(-40, 41, 4) for dy in range(-40, 41, 4)]
        return math.sqrt(np.mean([(r.maps.surface_z(x, y) - bump(x, y)) ** 2 for x, y in pts]))

    assert rms(ada) < rms(flat) * 0.9

    # ebene Fläche: Zellmitten bestätigen das Mesh, keine Verfeinerung
    _, _, plane = _probe(curved, [ProbeArea.from_rect("p", Rect(205, 185, 225, 205))],
                         ProbeSettings(spacing_mm=8, adaptive=True))
    assert not any("verfeinert" in l and not l.endswith(" 0 Zelle(n) verfeinert") for l in plane.log)


def test_probe_hop_stays_low_inside_area(bed):
    m, job, _ = _probe(bed, [ProbeArea.from_rect("rect", Rect(*RECT))])
    zs = [mv[2] for mv in m.moves]
    assert min(zs) < ProbeSettings().safe_z  # nicht jedes Mal auf safe_z


def test_pause_resume_and_cancel(bed):
    s = ProbeSettings(spacing_mm=12, adaptive=False)
    job = plan_probe_job([ProbeArea.from_rect("rect", Rect(*RECT))], s)
    seen: list[Progress] = []
    ctl = RunControl(on_progress=seen.append)
    ctl.pause()
    m = FakeMachine(bed)
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("r", ProbeRunner(m, ctl).run(job)))
    th.start()
    th.join(0.3)
    assert th.is_alive() and not m.probes  # pausiert
    ctl.resume()
    th.join(10)
    assert out["r"].ok and seen and seen[-1].fraction == pytest.approx(1.0)

    ctl2 = RunControl()
    m2 = FakeMachine(bed)
    orig = m2.probe_z

    def cancel_after_3(x, y, **kw):
        if len(m2.probes) >= 3:
            ctl2.cancel()
        return orig(x, y, **kw)

    m2.probe_z = cancel_after_3
    with pytest.raises(Cancelled):
        ProbeRunner(m2, ctl2).run(job)
    assert len(m2.probes) <= 5


# ---------------------------------------------------------------- Höhenmesh
def _plane_map():
    xs = np.arange(0, 101, 20.0)
    ys = np.arange(0, 81, 20.0)
    hm = HeightMap.empty("a", Rect(0, 0, 100, 80).to_polygon(), xs, ys)
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            hm.set(i, j, 1 + 0.02 * x - 0.01 * y + 0.0005 * x * y, MEASURED)
    return hm


def test_heightmap_interpolation_methods():
    hm = _plane_map()
    f = lambda x, y: 1 + 0.02 * x - 0.01 * y + 0.0005 * x * y
    for method in ("bilinear", "bicubic"):
        for x, y in [(10, 10), (55, 33), (99, 79), (0, 0)]:
            assert hm.z_at(x, y, method) == pytest.approx(f(x, y), abs=1e-6 if method == "bilinear" else 0.02)
    assert hm.z_at(41, 39, "nearest") == pytest.approx(f(40, 40))


def test_heightmap_set_json_roundtrip_and_offset(tmp_path):
    hm = _plane_map()
    hm.set(2, 2, None, FAILED)
    ms = HeightMapSet([hm], material="Pappel 3mm")
    p = tmp_path / "hm.json"
    ms.save(p)
    back = HeightMapSet.load(p)
    assert back.material == "Pappel 3mm"
    assert back.get("a").status[2, 2] == FAILED
    assert back.surface_z(55, 33) == pytest.approx(ms.surface_z(55, 33))
    assert back.z_offset(55, 33, reference_z=1.0) == pytest.approx(ms.surface_z(55, 33) - 1.0)
    assert json.loads(p.read_text())["format"].startswith("lumacut-heightmaps/")


# ---------------------------------------------------------------- Fokuskorrektur
def _flat_set(z_fn=lambda x, y: 3.0 + 0.05 * x):
    xs = np.arange(0, 101, 10.0)
    hm = HeightMap.empty("a", Rect(0, 0, 100, 100).to_polygon(), xs, xs)
    for j, y in enumerate(xs):
        for i, x in enumerate(xs):
            hm.set(i, j, z_fn(x, y), MEASURED)
    return HeightMapSet([hm])


def test_focus_compensation_segments_and_z():
    ms = _flat_set()
    g = "G21\nG90\nM3 I\nG0 X10 Y10\nG1 X30 Y10 S500 F1200\nG1 X30 Y20\nM5 I\n"
    out, rep = apply_focus_compensation(g, ms, FocusSettings(max_segment_mm=2))
    lines = out.splitlines()
    g1 = [l for l in lines if l.startswith("G1 X")]
    assert len(g1) == 10 + 5
    assert rep.segments_added == 13
    z_last = float(g1[9].split("Z")[1].split()[0])
    assert z_last == pytest.approx(3.0 + 0.05 * 30 + 7 - 1.5, abs=1e-3)
    assert all("S500" in l for l in g1[:10])            # S nur wo vorher S stand
    assert not any("S" in l for l in g1[10:])
    assert "F1200" in g1[0]
    assert "M3 I" in lines and "M5 I" in lines
    assert rep.z_min >= 3.0 + 2.0


def test_focus_compensation_g0_raises_before_and_lowers_after():
    ms = _flat_set(lambda x, y: 3.0 if x < 50 else 8.0)
    g = "G0 X10 Y50\nG0 X90 Y50\nG0 X10 Y50\n"
    out, _ = apply_focus_compensation(g, ms, start_z=20)
    L = [l for l in out.splitlines() if l.startswith("G0")]
    i_xy = L.index("G0 X90 Y50")
    assert L[i_xy - 1].startswith("G0 Z") and float(L[i_xy - 1][4:]) > 9  # erst hoch
    i_back = len(L) - 1 - L[::-1].index("G0 X10 Y50")
    assert L[i_back + 1].startswith("G0 Z") and float(L[i_back + 1][4:]) < 9  # dann runter


def test_focus_compensation_limits_feed_on_steep_z_and_handles_relative_inch():
    ms = _flat_set(lambda x, y: 3.0 + 0.5 * x)  # sehr steil
    out, rep = apply_focus_compensation("G0 X0 Y50\nG1 X20 Y50 F6000\n", ms)
    assert rep.feed_limited > 0 and rep.warnings
    out2, _ = apply_focus_compensation("G20\nG91\nG0 X1 Y1\nG1 X1 F60\n", _flat_set(), FocusSettings(max_segment_mm=100))
    assert "G1 X50.8 Y25.4" in out2


def test_focus_compensation_rejects_arcs_and_z():
    with pytest.raises(ValueError):
        apply_focus_compensation("G2 X10 Y10 I5 J0\n", _flat_set())
    with pytest.raises(ValueError):
        apply_focus_compensation("G1 X10 Y10 Z5\n", _flat_set())
    _, rep = apply_focus_compensation("G1 X200 Y200 F100\n", _flat_set())
    assert rep.outside_points and rep.warnings


# ---------------------------------------------------------------- Heatmap + Workflow
def test_heatmap_png(tmp_path, bed, scanned):
    _, _, res = _probe(bed, _areas())
    p = tmp_path / "heat.png"
    img = render_heatmap(res.maps, p, mosaic=scanned[3])
    assert p.exists() and img.ndim == 3 and img.shape[1] > scanned[3].image.shape[1] // 2
    img2 = render_heatmap(res.maps, px_per_mm=1)
    assert img2.shape[0] > 0


def test_workflow_end_to_end_with_design_and_reuse(tmp_path, bed, cal):
    m = FakeMachine(bed, position_error_mm=0.3, seed=2)
    cam = FakeCamera(m, bed, cal)
    phases = set()
    wf = ScanProbeWorkflow(m, cam, m, cal, ProbeSettings(spacing_mm=15),
                           control=RunControl(on_progress=lambda p: phases.add(p.phase)), settle_s=0)
    est = wf.estimate()
    assert est["total_s"] > 0
    res = wf.run(design_bounds=[Rect(80, 80, 140, 120)])
    assert [a.kind for a in res.areas] == ["rectangle"]
    assert res.maps.surface_z(100, 100) == pytest.approx(tilt(100, 100), abs=0.05)
    assert res.maps.surface_z(260, 240) is None            # Kreis nicht benutzt -> nicht geprobt
    assert {"scan", "probe"} <= phases
    p = tmp_path / "hm.json"
    res.maps.save(p)

    # Material unverändert -> Wiederverwendung mit 3 Kontrollmessungen
    n_before = len(m.probes)
    ok, notes = wf.try_reuse(HeightMapSet.load(p), res.mosaic)
    assert ok, notes
    assert len(m.probes) - n_before == 3

    # Material verschoben -> kein Reuse
    moved = SyntheticBed.with_objects(objects=[{"kind": "rect", "rect": (75, 70, 175, 150), "z": 3.0}])
    m2 = FakeMachine(moved)
    wf2 = ScanProbeWorkflow(m2, FakeCamera(m2, moved, cal), m2, cal, settle_s=0)
    ok2, notes2 = wf2.try_reuse(HeightMapSet.load(p), wf2.scan())
    assert not ok2 and notes2


def test_workflow_cancel_during_scan(bed, cal):
    m = FakeMachine(bed)
    ctl = RunControl()
    cam = FakeCamera(m, bed, cal)
    orig = cam.capture

    def cap():
        ctl.cancel()
        return orig()

    cam.capture = cap
    wf = ScanProbeWorkflow(m, cam, m, cal, control=ctl, settle_s=0)
    with pytest.raises(Cancelled):
        wf.run()


def test_qt_worker_emits_progress_and_result(qapp, bed, cal):
    pytest.importorskip("PySide6")
    from scanprobe.qt_bridge import ScanProbeWorker
    m = FakeMachine(bed)
    wf = ScanProbeWorkflow(m, FakeCamera(m, bed, cal), m, cal, ProbeSettings(spacing_mm=20), settle_s=0)
    worker = ScanProbeWorker(wf, design_bounds=[Rect(80, 80, 140, 120)])
    got, phases = [], set()
    worker.progress.connect(lambda ph, *a: phases.add(ph))
    worker.finished_ok.connect(got.append)
    worker.failed.connect(lambda msg: got.append(msg))
    worker.start()
    assert worker.wait(60000)
    qapp.processEvents()
    assert got and not isinstance(got[0], str), got
    assert got[0].maps.surface_z(100, 100) == pytest.approx(tilt(100, 100), abs=0.05)
    assert "probe" in phases
