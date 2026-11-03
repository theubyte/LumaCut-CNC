"""Free start corner inside a fill block (planner + G-code writer).

A hatch block may be entered at any of its four corners – first / last row ×
row start / row end – instead of only at its first or last point. The rows,
their spacing and the bidirectional / unidirectional rule stay the same.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import replace

import pytest

from _pi_guard import pi_check
from lumacut_canvas.hatch import (FORWARD, REVERSED, ROWS_FLIPPED, ROWS_REVERSED,
                                  fill_block_entries, fill_block_rows, fill_block_variant,
                                  fill_segments, hatch_lines, nearest_fill_entry)
from lumacut_job.planner import (fill_travel_length, improve_fill_block_order,
                                 order_fill_blocks_nearest)

START = (30.0, 30.0)
SQUARE_WITH_HOLE = [[(0, 0), (20, 0), (20, 12), (0, 12)], [(6, 3), (14, 3), (14, 9), (6, 9)]]


def _undirected(blocks):
    return sorted(sorted(tuple(sorted(seg)) for seg in b) for b in blocks)


def _dir(seg):
    (ax, ay), (bx, by) = seg
    d = math.hypot(bx - ax, by - ay)
    return round((bx - ax) / d, 6), round((by - ay) / d, 6)


def _row_dirs(block):
    return [_dir(row[0]) for row in fill_block_rows(block)]


def _shifted(block, dx, dy):
    return [((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)) for a, b in block]


def _hatch_block(x, y, w, h, step=0.5, bidirectional=True):
    return _shifted(hatch_lines([[(0, 0), (w, 0), (w, h), (0, h)]], step, 0.0, bidirectional),
                    x, y)


def _layout(n, seed, bidirectional=True):
    rnd = random.Random(seed)
    return [_hatch_block(rnd.uniform(10, 370), rnd.uniform(10, 370), rnd.uniform(2, 9),
                         rnd.uniform(1, 7), 0.5, bidirectional) for _ in range(n)]


def _plan(blocks, corners, reversible=True):
    greedy = order_fill_blocks_nearest(blocks, START, reversible, corners)
    return greedy, improve_fill_block_order(greedy, START, reversible, corners=corners)


# --- Rows and variants ----------------------------------------------------------------

@pytest.mark.parametrize("bidirectional", [True, False])
def test_rows_group_the_pieces_of_one_scan_line(bidirectional):
    block = hatch_lines(SQUARE_WITH_HOLE, 1.0, 0.0, bidirectional)
    rows = fill_block_rows(block)
    assert len(rows) == 12                       # one row per scan line
    assert sorted(len(r) for r in rows) == [1] * 6 + [2] * 6   # the hole splits six lines
    assert [s for r in rows for s in r] == block
    dirs = _row_dirs(block)
    if bidirectional:
        assert all(a != b for a, b in zip(dirs, dirs[1:]))
    else:
        assert len(set(dirs)) == 1


def test_crosshatch_rows_cover_both_angles():
    block = fill_segments(SQUARE_WITH_HOLE, "crosshatch", 1.0, 30.0, True)
    rows = fill_block_rows(block)
    assert [s for r in rows for s in r] == block
    assert len({tuple(abs(c) for c in d) for d in _row_dirs(block)}) == 2
    for row in rows:                             # every row is one straight line, in order
        u = _dir(row[0])
        for a, b in zip(row, row[1:]):
            assert _dir(b) == u
            assert (b[0][0] - a[1][0]) * u[0] + (b[0][1] - a[1][1]) * u[1] >= -1e-9


@pytest.mark.parametrize("bidirectional", [True, False])
@pytest.mark.parametrize("variant", [FORWARD, REVERSED, ROWS_REVERSED, ROWS_FLIPPED])
def test_variants_keep_lines_rows_and_direction_rule(bidirectional, variant):
    block = fill_segments(SQUARE_WITH_HOLE, "hatch", 1.0, 20.0, bidirectional)
    out = fill_block_variant(block, variant)
    assert _undirected([out]) == _undirected([block])
    assert len(fill_block_rows(out)) == len(fill_block_rows(block))
    dirs = _row_dirs(out)
    if bidirectional:
        assert all(a != b for a, b in zip(dirs, dirs[1:]))   # still alternating
    else:
        assert len(set(dirs)) == 1                            # still one direction
    entries = {v: (s, e) for s, e, v in fill_block_entries(block, True, True)}
    assert (out[0][0], out[-1][1]) == entries[variant]


def test_entries_per_block_kind():
    block = hatch_lines(SQUARE_WITH_HOLE, 1.0)
    four = fill_block_entries(block, True, True)
    assert [v for _, _, v in four] == [FORWARD, REVERSED, ROWS_REVERSED, ROWS_FLIPPED]
    assert len({s for s, _, _ in four}) == 4 and {s for s, _, _ in four} == {e for _, e, _ in four}
    assert [v for _, _, v in fill_block_entries(block, True, False)] == [FORWARD, REVERSED]
    assert [v for _, _, v in fill_block_entries(block, False, True)] == [FORWARD]
    one_row = [((0, 0), (5, 0)), ((7, 0), (9, 0))]
    assert len(fill_block_entries(one_row, True, True)) == 2   # corners = the two ends
    assert fill_block_entries([], True, True) == []
    with pytest.raises(ValueError):
        fill_block_variant(block, 7)


def test_nearest_entry_picks_the_corner_and_ties_keep_the_block():
    block = _hatch_block(0, 0, 10, 5, 1.0)          # 5 rows: (0,0.5) … ends at (10,4.5)
    rows = fill_block_rows(block)
    assert block[0][0] == (0, 0.5) and block[-1][1] == (10, 4.5)
    d, out = nearest_fill_entry(block, (11, 0), True, True)    # bottom right corner
    assert out[0][0] == rows[0][-1][1] == (10, 0.5) and d == pytest.approx(math.hypot(1, 0.5))
    assert out == fill_block_variant(block, ROWS_FLIPPED)
    _, out = nearest_fill_entry(block, (-1, 5), True, True)    # top left corner
    assert out == fill_block_variant(block, ROWS_REVERSED)
    _, out = nearest_fill_entry(block, (11, 0), True, False)   # old rule: start or end
    assert out[0][0] in ((0, 0.5), (10, 4.5))
    _, out = nearest_fill_entry(block, (5, 2.5), True, True)   # all four equally far
    assert out == block
    assert nearest_fill_entry(block, None, True, True) == (0.0, block)


# --- Planner --------------------------------------------------------------------------

def test_textbook_case_corner_entry_removes_the_detour():
    """Blocks in a row, an odd number of rows each: a block ends diagonally
    opposite its start, so start/end entry zigzags; a corner entry runs along."""
    blocks = [_hatch_block(40 + 15 * i, 30, 10, 21, 1.0) for i in range(6)]
    assert len(fill_block_rows(blocks[0])) == 21
    _, old = _plan(blocks, False)
    _, new = _plan(blocks, True)
    o, n = fill_travel_length(old, START), fill_travel_length(new, START)
    assert n < 0.8 * o
    assert _undirected(new) == _undirected(blocks)
    used = {next(v for s, e, v in fill_block_entries(b, True, True)
                 if s == nb[0][0] and e == nb[-1][1])
            for b in blocks for nb in new if _undirected([b]) == _undirected([nb])}
    assert used & {ROWS_REVERSED, ROWS_FLIPPED}


def test_grid_of_tiles_saves_travel():
    """A sheet of small engraved tags (6 × 6 grid, 19 rows each)."""
    blocks = [_hatch_block(40 + 12 * i, 40 + 13 * j, 9, 9.5, 0.5)
              for i in range(6) for j in range(6)]
    _, old = _plan(blocks, False)
    _, new = _plan(blocks, True)
    assert fill_travel_length(new, START) < 0.75 * fill_travel_length(old, START)


@pytest.mark.parametrize("bidirectional", [True, False])
def test_corners_shorten_the_travel_on_random_layouts(bidirectional):
    old_sum = new_sum = 0.0
    for seed in range(10):
        for n in (8, 30, 70):
            blocks = _layout(n, seed, bidirectional)
            greedy, new = _plan(blocks, True)
            _, old = _plan(blocks, False)
            g, nw = fill_travel_length(greedy, START), fill_travel_length(new, START)
            assert nw <= g + 1e-9
            assert _undirected(new) == _undirected(blocks)
            for b in new:
                dirs = _row_dirs(b)
                if bidirectional:
                    assert all(x != y for x, y in zip(dirs, dirs[1:]))
                else:
                    assert len(set(dirs)) == 1
            old_sum += fill_travel_length(old, START)
            new_sum += nw
    assert new_sum < old_sum   # scattered blocks: small but consistent gain


def test_planned_corners_match_the_gcode_writer():
    from lumacut_canvas.gcode import order_fill_blocks
    for seed in range(6):
        _, new = _plan(_layout(50, seed), True)
        assert order_fill_blocks(new, START, True, True) == new
        assert order_fill_blocks(new, None, True, True) == new


def test_fixed_order_blocks_ignore_corners():
    blocks = _layout(20, 4)
    greedy = order_fill_blocks_nearest(blocks, START, False, True)
    opt = improve_fill_block_order(greedy, START, False, corners=True)
    assert all(b in blocks for b in opt)


def test_deterministic_and_runtime_bounded_with_corners():
    blocks = _layout(80, 9)
    assert _plan(blocks, True) == _plan([list(b) for b in blocks], True)
    greedy = order_fill_blocks_nearest(_layout(1500, 11), START, True, True)
    t = time.perf_counter()
    opt = improve_fill_block_order(greedy, START, True, corners=True)
    assert time.perf_counter() - t < 15.0
    assert fill_travel_length(opt, START) <= fill_travel_length(greedy, START)


# --- Document / G-code ----------------------------------------------------------------

def _doc(shapes, **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 1.0)
    layer.setdefault("hatch_outline", False)
    doc.update_layer(lid, **layer)
    for x, y, w, h in shapes:
        doc.add_shape(Shape("rect", Geometry(x, y, w, h), lid))
    return doc


ROW = [(20 + 15 * i, 20, 10, 21) for i in range(6)]   # 21 rows at 1 mm


def _burns(g, first_pass_only=True):
    """Powered G1 segments (start, end) in order."""
    out, pos = [], None
    for line in g.splitlines():
        if first_pass_only and line.startswith("; PASS 2"):
            break
        if not line.startswith(("G0 ", "G1 ")):
            continue
        w = dict((t[0], float(t[1:])) for t in line.split()[1:])
        p = (w["X"], w["Y"])
        if line.startswith("G1 ") and w.get("S", 0) > 0:
            out.append((pos, p))
        pos = p
    return out


@pytest.mark.parametrize("mode,flag", [("hatch", True), ("crosshatch", True),
                                       ("offset", False)])
def test_job_layer_flag_only_for_line_fills(qapp, mode, flag):
    from lumacut_canvas.export import JobLayer, job_layers
    (jl,) = job_layers(_doc(ROW[:2], fill_mode=mode))
    assert jl.fill_free_corner is flag
    assert JobLayer("x", "x", 50, 1000, 1, []).fill_free_corner is False


def test_send_gcode_uses_corners_and_matches_the_plan(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimize_layers
    doc = _doc(ROW, passes=2)
    (jl,) = job_layers(doc)
    (new,) = optimize_layers([jl], START)
    (old,) = optimize_layers([replace(jl, fill_free_corner=False)], START)
    g_new, g_old = layers_to_gcode([new]), layers_to_gcode([old])
    pi_check(g_new)
    e_new, e_old = estimate_gcode(g_new), estimate_gcode(g_old)
    assert e_new.cut_length_mm == pytest.approx(e_old.cut_length_mm)
    assert e_new.travel_length_mm < 0.85 * e_old.travel_length_mm
    planned = [((round(a[0], 3), round(a[1], 3)), (round(b[0], 3), round(b[1], 3)))
               for blk in new.fills for a, b in blk]
    assert _burns(g_new) == planned               # pass 1 lasers exactly the plan
    assert g_new.count("; PASS ") == 2


@pytest.mark.parametrize("bidirectional", [True, False])
def test_overscan_and_scan_offset_follow_the_chosen_direction(qapp, bidirectional):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    from lumacut_job.planner import optimize_layers
    doc = _doc(ROW, fill_overscan_mm=2.0, hatch_bidirectional=bidirectional)
    (jl,) = job_layers(doc)
    (new,) = optimize_layers([replace(jl, fill_scan_offset_mm=0.4)], START)
    assert any(b not in jl.fills and [(q, p) for p, q in reversed(b)] not in jl.fills
               for b in new.fills)                 # at least one corner entry used
    g = layers_to_gcode([new])
    pi_check(g)
    lines = [l for l in g.splitlines() if l.startswith(("G0 ", "G1 "))]
    burns = _burns(g)
    planned = [s for blk in new.fills for s in blk]
    assert len(burns) == len(planned)
    for (a, b), (pa, pb) in zip(burns, planned):
        u = _dir((pa, pb))
        assert _dir((a, b)) == u                   # same direction as planned
        # shifted by half the offset against the direction of travel
        assert a[0] == pytest.approx(pa[0] - 0.2 * u[0], abs=2e-3)
        assert b[0] == pytest.approx(pb[0] - 0.2 * u[0], abs=2e-3)
    # every burn has laser-off run-up and run-out
    for i, l in enumerate(lines):
        if l.startswith("G1 ") and not l.endswith(" S0"):
            assert lines[i - 1].endswith(" S0") and lines[i + 1].endswith(" S0")


def test_offset_fill_is_unchanged_by_the_corner_rule(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import optimize_layers
    (jl,) = job_layers(_doc(ROW, fill_mode="offset"))
    (opt,) = optimize_layers([jl], START)
    assert all(b in jl.fills for b in opt.fills)


def test_single_block_document_output_unchanged(qapp):
    """One block entered from an unknown head position keeps its generated order."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import document_to_gcode, layers_to_gcode
    doc = _doc(ROW[:1])
    (jl,) = job_layers(doc)
    assert document_to_gcode(doc) == layers_to_gcode([replace(jl, fill_free_corner=False)])
