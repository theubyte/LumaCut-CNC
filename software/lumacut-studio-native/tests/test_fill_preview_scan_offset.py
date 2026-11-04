"""Canvas fill preview with the scanning offset: preview lines = burned lines of the G-code."""

from __future__ import annotations

import pytest

from test_scan_offset import _doc, _table


@pytest.fixture(autouse=True)
def _restore_active_table():
    from lumacut_job import scan_offset
    old = scan_offset.active_table()
    scan_offset._PREVIEW_CACHE.clear()
    yield
    scan_offset.set_active_table(old)
    scan_offset._PREVIEW_CACHE.clear()


def _pass1_burns(g):
    """{layer name: powered moves of pass 1} (machine mm) from planned G-code."""
    out, pos, layer, pass_no = {}, None, None, 0
    for line in g.splitlines():
        if line.startswith("; LAYER "):
            layer = line[8:]
            out.setdefault(layer, [])
            continue
        if line.startswith("; PASS "):
            pass_no = int(line.split()[2])
            continue
        if not line.startswith(("G0 ", "G1 ")):
            continue
        w = dict((t[0], float(t[1:])) for t in line.split()[1:])
        p = (w.get("X", pos[0] if pos else 0.0), w.get("Y", pos[1] if pos else 0.0))
        if line.startswith("G1") and w.get("S", 0) > 0 and pos is not None and pass_no == 1:
            out[layer].append((pos, p))
        pos = p
    return out


def _to_machine(preview):
    from lumacut_canvas.workarea import screen_to_machine
    return {lid: [(screen_to_machine(*a), screen_to_machine(*b)) for a, b in segs]
            for lid, segs in preview.items()}


def _close(seg_a, seg_b, tol=2e-3):
    return all(abs(p - q) <= tol for u, v in zip(seg_a, seg_b) for p, q in zip(u, v))


def _assert_preview_is_gcode(doc, table):
    from lumacut_job.planner import optimized_document_gcode
    from lumacut_job.scan_offset import preview_fill_lines
    preview = preview_fill_lines(doc, table)
    assert preview is not None
    g = optimized_document_gcode(doc, scan_offsets=table)
    burns = _pass1_burns(g)
    machine = _to_machine(preview)
    names = {l.id: l.name for l in doc.layers}
    checked = 0
    for lid, segs in machine.items():
        got = burns.get(names[lid], [])
        assert len(got) >= len(segs)
        # fill is lasered first in every pass, contours follow
        for s, b in zip(segs, got):
            assert _close(s, b), (s, b)
        checked += len(segs)
    assert checked > 0
    return preview


# --- helper layer ------------------------------------------------------------------------
def test_none_without_active_shift():
    from lumacut_job.scan_offset import preview_fill_lines
    doc = _doc(speed=3000)
    assert preview_fill_lines(doc, None) is None
    assert preview_fill_lines(doc, _table((3000, 0.4), enabled=False)) is None
    assert preview_fill_lines(doc, _table((3000, 0.0))) is None          # all offsets zero
    assert preview_fill_lines(_doc(fill_mode="offset", speed=3000), _table((3000, 0.4))) is None
    assert preview_fill_lines(_doc(fill_mode="none", speed=3000), _table((3000, 0.4))) is None
    assert preview_fill_lines(doc) is None                                # default: app table off


def test_bidirectional_lines_shift_half_against_travel():
    from lumacut_canvas.export import layer_fill_blocks
    from lumacut_job.scan_offset import preview_fill_lines
    doc = _doc(((40, 40, 20, 10),), speed=3000, line_interval_mm=2.0)
    plain = sorted(layer_fill_blocks(doc, doc.layers[0])[0][1], key=lambda s: s[0][1])
    shifted = preview_fill_lines(doc, _table((3000, 0.4)))[doc.layers[0].id]
    assert len(shifted) == len(plain)
    by_y = {round(a[1], 6): (a, b) for a, b in shifted}
    moved = []
    for a, b in plain:
        sa, sb = by_y[round(a[1], 6)]
        lo, hi = sorted((a[0], b[0]))
        slo, shi = sorted((sa[0], sb[0]))
        assert shi - slo == pytest.approx(hi - lo)            # same length
        dx = slo - lo
        assert abs(dx) == pytest.approx(0.2)                   # half the offset
        going_right = sb[0] > sa[0]
        assert (dx < 0) == going_right                         # against the direction of travel
        moved.append(dx)
    assert {round(d, 6) for d in moved} == {-0.2, 0.2}         # back and forth alternate


def test_unidirectional_all_lines_move_the_same_way():
    from lumacut_job.scan_offset import preview_fill_lines
    doc = _doc(((40, 40, 20, 10),), speed=3000, hatch_bidirectional=False)
    segs = preview_fill_lines(doc, _table((3000, 0.4)))[doc.layers[0].id]
    assert len({(b[0] > a[0]) for a, b in segs}) == 1
    lows = {round(min(a[0], b[0]), 6) for a, b in segs}
    assert len(lows) == 1 and abs(lows.pop() - 40.0) == pytest.approx(0.2)


@pytest.mark.parametrize("layer", [
    dict(),                                                    # bidirectional hatch
    dict(hatch_bidirectional=False),
    dict(fill_mode="crosshatch"),
    dict(hatch_angle=30.0, line_interval_mm=1.5),
    dict(fill_overscan_mm=2.0),
    dict(passes=3, hatch_outline=True),
    dict(fill_grouping="together"),
])
def test_preview_equals_pass_one_of_the_gcode(layer):
    layer.setdefault("speed", 3000)
    shapes = [(20 + 31 * (i % 5), 20 + 23 * (i // 5), 18 + (i % 3) * 3, 11 + (i % 2) * 5)
              for i in range(15)]
    _assert_preview_is_gcode(_doc(shapes, **layer), _table((1000, 0.1), (6000, 0.6)))


def test_preview_equals_gcode_over_several_layers_and_speeds():
    from lumacut_canvas.model import Geometry, Layer, Shape
    doc = _doc(((20, 20, 30, 12), (80, 30, 25, 25)), speed=2000, hatch_outline=True)
    for name, speed, mode in (("Schnell", 6000, "hatch"), ("Ring", 3000, "offset"),
                              ("Kreuz", 4500, "crosshatch")):
        lay = doc.add_layer(Layer(name, fill_mode=mode, line_interval_mm=1.5,
                                  speed=speed, hatch_outline=False))
        for k in range(3):
            doc.add_shape(Shape("rect", Geometry(30 + 60 * k, 120 + 40 * len(name) % 90, 22, 14),
                                lay.id))
    table = _table((2000, 0.2), (6000, 0.5))
    preview = _assert_preview_is_gcode(doc, table)
    ring = next(l for l in doc.layers if l.name == "Ring")
    # offset fill (rings) is never shifted: same lines as the plain geometry
    from lumacut_canvas.export import layer_fill_blocks
    plain = {tuple(map(tuple, s)) for _ids, segs in layer_fill_blocks(doc, ring) for s in segs}
    got = {tuple(map(tuple, s)) for s in preview[ring.id]}
    assert len(got) == len(plain)
    assert all(any(_close(g, p, 1e-6) for p in plain) for g in list(got)[:50])


def test_shift_is_clamped_at_the_cutting_area_edge_like_gcode():
    from lumacut_canvas.workarea import MACHINE_X_MAX, MACHINE_X_MIN, to_machine
    # rectangle touching the edge of the cutting area (work X 0 = machine X max)
    doc = _doc(((0, 40, 20, 10),), speed=3000)
    assert to_machine(0, 40)[0] == pytest.approx(MACHINE_X_MAX)
    pre = _to_machine(_assert_preview_is_gcode(doc, _table((3000, 1.0))))
    xs = [p[0] for a, b in pre[doc.layers[0].id] for p in (a, b)]
    assert MACHINE_X_MIN - 1e-6 <= min(xs) and max(xs) <= MACHINE_X_MAX + 1e-6
    assert max(xs) == pytest.approx(MACHINE_X_MAX)      # clamped, not pushed outside


def test_cache_reuses_plan_and_follows_changes():
    from lumacut_job import scan_offset
    doc = _doc(((40, 40, 20, 10), (90, 40, 20, 10)), speed=3000)
    t = _table((3000, 0.4))
    first = scan_offset.preview_fill_lines(doc, t)
    key = scan_offset._PREVIEW_CACHE["key"]
    first[doc.layers[0].id].clear()                       # caller may mutate its copy
    assert scan_offset.preview_fill_lines(doc, t)[doc.layers[0].id]
    assert scan_offset._PREVIEW_CACHE["key"] == key
    doc.update_layer(doc.layers[0].id, speed=1000)        # other offset → new plan
    _assert_preview_is_gcode(doc, _table((1000, 0.8), (3000, 0.4)))
    assert scan_offset._PREVIEW_CACHE["key"] != key


def test_fill_burn_segments_matches_writer_without_offset():
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import fill_burn_segments, layers_to_gcode
    doc = _doc(((20, 20, 30, 12), (80, 30, 25, 25)), speed=2000, passes=2, hatch_outline=True)
    layers = job_layers(doc)
    burns = fill_burn_segments(layers)
    g = _pass1_burns(layers_to_gcode(layers))
    (segs,) = burns
    assert segs and all(_close(s, b) for s, b in zip(segs, g[doc.layers[0].name]))
    from lumacut_canvas.export import JobLayer
    assert fill_burn_segments([JobLayer("x", "x", 10, 1000, 1, [])]) == [[]]


# --- canvas widget -----------------------------------------------------------------------
def _preview_segments(ed):
    return [((l.x1(), l.y1()), (l.x2(), l.y2())) for _c, lines in ed.fill_preview.lines
            for l in lines]


def test_canvas_fill_preview_draws_shifted_lines(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.scan_offset import preview_fill_lines, set_active_table
    doc = _doc(((40, 40, 20, 10), (90, 60, 15, 15)), speed=3000)
    ed = CanvasEditor(doc)
    ed.fill_preview.rebuild()
    assert ed.fill_preview.wait()
    plain = _preview_segments(ed)
    assert not ed.fill_preview.scan_offset_applied
    set_active_table(_table((3000, 0.4)))
    ed.fill_preview.rebuild()
    assert ed.fill_preview.wait()
    shifted = _preview_segments(ed)
    assert ed.fill_preview.scan_offset_applied and len(shifted) == len(plain)
    assert sorted(shifted) != sorted(plain)
    want = preview_fill_lines(doc)[doc.layers[0].id]
    assert all(_close(s, w, 1e-9) for s, w in zip(shifted, want))
    set_active_table(None)
    ed.fill_preview.rebuild()
    assert ed.fill_preview.wait()
    assert _preview_segments(ed) == plain and not ed.fill_preview.scan_offset_applied
    ed.grab()


def test_canvas_preview_hidden_layer_and_planner_error(qapp, monkeypatch):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job import scan_offset
    doc = _doc(((40, 40, 20, 10),), speed=3000)
    scan_offset.set_active_table(_table((3000, 0.4)))
    ed = CanvasEditor(doc)
    ed.fill_preview.rebuild()
    assert ed.fill_preview.wait()
    assert ed.fill_preview.line_count() > 0
    doc.update_layer(doc.layers[0].id, visible=False)
    ed.fill_preview.rebuild()
    assert ed.fill_preview.wait()
    assert ed.fill_preview.line_count() == 0
    doc.update_layer(doc.layers[0].id, visible=True)

    def boom(*_a, **_k):
        raise ValueError("zu viele Linien")
    monkeypatch.setattr(scan_offset, "preview_fill_request", boom)
    ed.fill_preview.rebuild()                       # falls back to the plain fill geometry
    assert ed.fill_preview.line_count() > 0 and not ed.fill_preview.scan_offset_applied


@pytest.fixture
def win(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_changing_the_table_refreshes_the_fill_preview(win):
    from lumacut_canvas.model import Geometry, Shape
    tools = win.job_tools
    doc = win.canvas.document
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch", line_interval_mm=2.0, speed=2000.0,
                     hatch_outline=False)
    doc.add_shape(Shape("rect", Geometry(20, 20, 20, 10), lid))
    fp = win.canvas.fill_preview
    fp.rebuild()
    assert fp.wait()
    before = _preview_segments(win.canvas)
    calls = []
    orig = fp.schedule
    fp.schedule = lambda: (calls.append(1), orig())
    tools.scan_offset(_table((2000, 0.4)))
    assert calls
    fp.rebuild()
    assert fp.wait()
    assert fp.scan_offset_applied and sorted(_preview_segments(win.canvas)) != sorted(before)
    tools.scan_offset(_table((2000, 0.4), enabled=False))
    fp.rebuild()
    assert fp.wait()
    assert sorted(_preview_segments(win.canvas)) == sorted(before)
