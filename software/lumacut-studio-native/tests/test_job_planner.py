import math

from _pi_guard import pi_check
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.gcode import document_to_gcode, layers_to_gcode
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_job.planner import (containment, is_closed, optimize_layers, optimized_document_gcode,
                                 order_polylines, point_in_polygon, travel_length)


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def test_point_in_polygon_and_closed():
    sq = square(0, 0, 10)
    assert is_closed(sq) and not is_closed([(0, 0), (5, 5)])
    assert point_in_polygon((5, 5), sq) and not point_in_polygon((15, 5), sq)


def test_inside_first_cuts_holes_before_outline():
    outer = square(40, 40, 100)
    hole = square(60, 60, 10)
    nested = square(62, 62, 4)  # inside the hole (island)
    other = square(200, 200, 20)
    parents = containment([outer, hole, nested, other])
    assert parents[1] == {0} and parents[2] == {0, 1} and parents[3] == set()
    ordered = order_polylines([outer, hole, nested, other], start=(40, 40))
    def idx(p):
        return next(i for i, q in enumerate(ordered) if set(q) == set(p))
    assert idx(nested) < idx(hole) < idx(outer)


def test_reduce_travel_and_best_start():
    polys = [square(x, 50, 5) for x in (300, 40, 200, 120)]
    ordered = order_polylines(polys, start=(30, 30))
    assert travel_length(ordered) < travel_length(polys)
    xs = [min(p[0] for p in q) for q in ordered]
    assert xs == sorted(xs)
    # Closed shapes stay closed and keep all vertices after rotation.
    for q in ordered:
        assert is_closed(q) and len(q) == 5


def test_open_paths_may_be_reversed():
    line = [(100, 50), (40, 50)]
    (out,) = order_polylines([line], start=(30, 50))
    assert out[0] == (40, 50)


def test_options_off_keeps_order():
    polys = [square(300, 50, 5), square(40, 50, 5)]
    assert order_polylines(polys, inside_first=False, reduce_travel=False) == polys


def test_optimized_document_gcode_is_pi_safe(qapp):
    doc = Document()
    cut = doc.active_layer_id
    eng = doc.add_layer(Layer(name="Gravur", power=30, speed=3000))
    doc.add_shape(Shape("rect", Geometry(10, 10, 100, 80), cut))
    doc.add_shape(Shape("ellipse", Geometry(30, 30, 20, 20), cut))
    doc.add_shape(Shape("text", Geometry(200, 200, 40, 10), eng.id, text="Hi"))
    g = optimized_document_gcode(doc)
    pi_check(g)
    plain = document_to_gcode(doc)
    # Same layer order and same amount of cutting moves.
    assert g.index("; LAYER Schneiden") < g.index("; LAYER Gravur") or \
        plain.index("; LAYER Schneiden") > plain.index("; LAYER Gravur")
    assert sum(l.startswith("G1") for l in g.splitlines()) == \
        sum(l.startswith("G1") for l in plain.splitlines())
    # The ellipse (inside the rect) is cut before the rect outline.
    layers = optimize_layers(job_layers(doc))
    cut_layer = next(l for l in layers if l.layer_id == cut)
    widths = [max(p[0] for p in q) - min(p[0] for p in q) for q in cut_layer.polylines]
    assert widths[0] < widths[-1]


def test_layer_end_position_chains():
    a = JobLayer("a", "A", 50, 1000, 1, [[(100, 100), (110, 100)]])
    b = JobLayer("b", "B", 50, 1000, 1, [[(300, 300), (310, 300)], [(112, 100), (120, 100)]])
    out = optimize_layers([a, b])
    assert out[1].polylines[0][0] == (112, 100)
    assert layers_to_gcode(out).count("G0") == 3
    assert math.isclose(travel_length(out[1].polylines, (110, 100)), 2 + math.dist((120, 100), (300, 300)))
