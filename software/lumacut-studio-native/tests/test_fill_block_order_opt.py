"""2-opt / Or-opt pass over the nearest-neighbour fill block order (planner)."""

from __future__ import annotations

import random
import time

import pytest

from _pi_guard import pi_check
from lumacut_job.planner import (FILL_OPT_MAX_BLOCKS, fill_travel_length,
                                 improve_fill_block_order, order_fill_blocks_nearest)

START = (30.0, 30.0)


def _hatch_block(x, y, w, h, step=0.5):
    """Bidirectional hatch lines of a w × h rectangle at (x, y)."""
    segs = []
    for k in range(int(h / step) + 1):
        a, b = (x, y + k * step), (x + w, y + k * step)
        segs.append((a, b) if k % 2 == 0 else (b, a))
    return segs


def _ring_block(x, y, r):
    """Offset-like block: concentric squares, entered at its first point."""
    segs = []
    for k in range(3):
        d = r - k
        pts = [(x - d, y - d), (x + d, y - d), (x + d, y + d), (x - d, y + d), (x - d, y - d)]
        segs += list(zip(pts, pts[1:]))
    return segs


def _layout(n, seed, kind="hatch"):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        x, y = rnd.uniform(10, 370), rnd.uniform(10, 370)
        out.append(_hatch_block(x, y, rnd.uniform(2, 8), rnd.uniform(1, 6)) if kind == "hatch"
                   else _ring_block(x, y, rnd.uniform(3, 6)))
    return out


def _undirected(blocks):
    return sorted(sorted(tuple(sorted(seg)) for seg in b) for b in blocks)


def _reverse(block):
    return [(b, a) for a, b in reversed(block)]


def _both(blocks, reversible):
    greedy = order_fill_blocks_nearest(blocks, START, reversible)
    return greedy, improve_fill_block_order(greedy, START, reversible)


@pytest.mark.parametrize("reversible,kind", [(True, "hatch"), (False, "rings")])
def test_travel_never_longer_and_clearly_shorter_than_greedy(reversible, kind):
    greedy_sum = opt_sum = 0.0
    for seed in range(12):
        for n in (8, 25, 60):
            greedy, opt = _both(_layout(n, seed, kind), reversible)
            g, o = fill_travel_length(greedy, START), fill_travel_length(opt, START)
            assert o <= g + 1e-9
            greedy_sum += g
            opt_sum += o
    assert opt_sum < 0.93 * greedy_sum   # at least 7 % less fill travel overall


def test_textbook_case_where_greedy_leaves_a_block_behind():
    """Blocks on a line: greedy runs right first and leaves the left one behind."""
    xs = [30 + 2 * i for i in range(1, 11)] + [26.5]
    blocks = [[((x, 30.0), (x + 0.5, 30.0))] for x in xs]
    greedy, opt = _both(blocks, True)
    g, o = fill_travel_length(greedy, START), fill_travel_length(opt, START)
    assert o < 0.75 * g
    assert [min(b[0][0][0], b[0][1][0]) for b in opt] == sorted(xs)   # left one first


@pytest.mark.parametrize("reversible", [True, False])
def test_blocks_stay_whole_and_fixed_blocks_are_never_reversed(reversible):
    blocks = _layout(40, 3, "hatch" if reversible else "rings")
    _, opt = _both(blocks, reversible)
    assert len(opt) == len(blocks)
    assert _undirected(opt) == _undirected(blocks)
    for b in opt:
        if reversible:
            assert b in blocks or _reverse(b) in blocks
        else:
            assert b in blocks   # ring order inside an offset block is kept


def test_planned_entries_match_the_gcode_writer():
    """The G-code writer re-decides each block's direction; it must keep the plan."""
    from lumacut_canvas.gcode import order_fill_blocks
    for seed in range(6):
        _, opt = _both(_layout(50, seed), True)
        assert order_fill_blocks(opt, START, True) == opt
        assert order_fill_blocks(opt, None, True) == opt   # first layer: head position unknown


def test_deterministic_and_stable():
    blocks = _layout(80, 7)
    _, a = _both(blocks, True)
    _, b = _both([list(x) for x in blocks], True)
    assert a == b
    again = improve_fill_block_order(a, START, True)
    assert fill_travel_length(again, START) <= fill_travel_length(a, START) + 1e-9


def test_trivial_inputs_and_bounds():
    one = _layout(1, 1)
    assert improve_fill_block_order([], START) == []
    assert improve_fill_block_order(one, START) == one
    assert improve_fill_block_order([[]] + one, START) == one
    greedy = order_fill_blocks_nearest(_layout(30, 2), START)
    assert improve_fill_block_order(greedy, START, budget=0) == greedy
    small = improve_fill_block_order(greedy, START, budget=50)
    assert fill_travel_length(small, START) <= fill_travel_length(greedy, START) + 1e-9
    many = [[((float(i % 50), float(i // 50)), (i % 50 + 0.5, float(i // 50)))]
            for i in range(FILL_OPT_MAX_BLOCKS + 1)]
    assert improve_fill_block_order(many, START) == many


def test_runtime_is_bounded_for_many_blocks():
    greedy = order_fill_blocks_nearest(_layout(1500, 11), START)
    t = time.perf_counter()
    opt = improve_fill_block_order(greedy, START)
    assert time.perf_counter() - t < 10.0   # budget ≈ 0.5 s here; generous for slow CI
    assert fill_travel_length(opt, START) <= fill_travel_length(greedy, START)


# --- Planner / G-code ---------------------------------------------------------------

def _doc(n=30, seed=5, **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 1.0)
    layer.setdefault("hatch_outline", False)
    doc.update_layer(lid, **layer)
    rnd = random.Random(seed)
    for _ in range(n):
        doc.add_shape(Shape("rect", Geometry(rnd.uniform(5, 360), rnd.uniform(5, 360),
                                             rnd.uniform(3, 10), rnd.uniform(3, 10)), lid))
    return doc


@pytest.mark.parametrize("mode", ["hatch", "offset"])
def test_send_gcode_has_less_travel_than_greedy_and_stays_valid(qapp, monkeypatch, mode):
    from lumacut_job import planner
    from lumacut_job.estimate import estimate_gcode
    doc = _doc(fill_mode=mode, passes=2)
    opt_g = planner.optimized_document_gcode(doc)
    pi_check(opt_g)
    monkeypatch.setattr(planner, "improve_fill_block_order", lambda b, *a, **k: b)
    greedy_g = planner.optimized_document_gcode(doc)
    opt, greedy = estimate_gcode(opt_g), estimate_gcode(greedy_g)
    assert opt.cut_length_mm == pytest.approx(greedy.cut_length_mm)
    assert opt.travel_length_mm < greedy.travel_length_mm
    assert opt_g.count("; PASS ") == 2 and opt_g.count("G0 ") < greedy_g.count("G0 ") + 1


def test_layer_fills_from_planner_match_the_lasered_order(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import optimize_layers
    doc = _doc()
    (jl,) = job_layers(doc)
    (opt,) = optimize_layers([jl], START)
    assert _undirected(opt.fills) == _undirected(jl.fills)
    greedy = order_fill_blocks_nearest(jl.fills, START)
    assert fill_travel_length(opt.fills, START) < fill_travel_length(greedy, START)
    (keep,) = optimize_layers([jl], START, reduce_travel=False)
    assert keep.fills == jl.fills
