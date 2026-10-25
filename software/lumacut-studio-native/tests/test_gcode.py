import re

import pytest

from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document, Geometry, Layer, Shape

ALLOWED = re.compile(r"^(;.*|G21|G90|M3 I|M5 I|M400|G0 X\d+\.\d{3} Y\d+\.\d{3}|"
                     r"G1 X\d+\.\d{3} Y\d+\.\d{3} F\d+ S\d+)$")


def test_gcode_matches_pi_rules(qapp):
    doc = Document()
    cut = doc.active_layer_id
    doc.update_layer(cut, power=100, speed=600, passes=2)
    eng = doc.add_layer(Layer(name="Gravur", power=50, speed=3000, passes=1))
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), cut))
    doc.add_shape(Shape("ellipse", Geometry(100, 100, 20, 20), eng.id))
    hidden = doc.add_layer(Layer(name="Aus", visible=False))
    doc.add_shape(Shape("line", Geometry(5, 5, 10, 0), hidden.id))
    g = document_to_gcode(doc)
    lines = g.splitlines()
    assert all(ALLOWED.match(l) for l in lines), [l for l in lines if not ALLOWED.match(l)]
    assert lines.count("M3 I") == 1 and lines[-2:] == ["M5 I", "M400"]
    assert "G0 X30.000 Y30.000" in lines  # Safezone-Versatz
    assert g.index("; LAYER Schneiden") < g.index("; LAYER Gravur")  # unterste Ebene zuerst
    assert "S255" in g and "S128" in g and "; LAYER Aus" not in g
    assert g.count("; PASS") == 3
    s_values = [int(v) for v in re.findall(r" S(\d+)", g)]
    assert all(0 <= v <= 255 for v in s_values)


def test_gcode_requires_visible_objects(qapp):
    with pytest.raises(ValueError):
        document_to_gcode(Document())
