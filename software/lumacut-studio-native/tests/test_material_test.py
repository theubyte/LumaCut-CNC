import pytest

from _pi_guard import pi_check
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document
from lumacut_job.material_test import (MaterialTestSpec, add_material_test, build_material_test,
                                       hatch_points)


def test_grid_layers_cover_power_and_speed_ranges():
    spec = MaterialTestSpec(columns=4, rows=3, power_min=10, power_max=40,
                            speed_min=600, speed_max=1800)
    layers, shapes = build_material_test(spec)
    assert spec.powers() == [10, 20, 30, 40] and spec.speeds() == [600, 1200, 1800]
    cells = [l for l in layers if l.name.startswith("Test P")]
    assert len(cells) == 12 and layers[0].name == "Test Beschriftung"
    assert {(l.power, l.speed) for l in cells} == {(p, s) for p in spec.powers() for s in spec.speeds()}
    texts = [s for s in shapes if s.kind == "text"]
    assert len(texts) == 4 + 3
    # Bottom layer runs first -> top-left cell (P10 F600) is the last layer.
    assert layers[-1].name == "Test P10% F600"


def test_hatch_fill_and_outline_mode():
    pts = hatch_points(0, 0, 10, 1, 0.5)
    assert pts[:4] == [(0, 0), (10, 0), (10, 0.5), (0, 0.5)]
    _, shapes = build_material_test(MaterialTestSpec(rows=1, columns=1, labels=False,
                                                     line_interval_mm=0))
    assert [s.kind for s in shapes] == ["rect"]


def test_validation():
    with pytest.raises(ValueError):
        build_material_test(MaterialTestSpec(columns=13))
    with pytest.raises(ValueError):
        build_material_test(MaterialTestSpec(x=340))  # does not fit
    with pytest.raises(ValueError):
        build_material_test(MaterialTestSpec(speed_max=9000))


def test_material_test_produces_pi_safe_gcode(qapp):
    doc = Document()
    layers = add_material_test(doc, MaterialTestSpec(columns=3, rows=2, line_interval_mm=0.5))
    assert len(doc.layers) == 1 + len(layers)
    g = document_to_gcode(doc)
    pi_check(g)
    assert g.count("; LAYER Test P") == 6
    assert g.rindex("; LAYER Test Beschriftung") > g.rindex("; LAYER Test P")


def test_insert_is_one_undo_step(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.qt_tools import insert_material_test
    ed = CanvasEditor()
    n0 = len(ed.document.layers)
    n = insert_material_test(ed, MaterialTestSpec(columns=2, rows=2))
    assert len(ed.document.layers) == n0 + n and ed.document.shapes
    ed.undo_stack.undo()
    assert len(ed.document.layers) == n0 and not ed.document.shapes
    ed.undo_stack.redo()
    assert len(ed.document.layers) == n0 + n
    ed.undo_stack.setClean()
    ed.deleteLater()
