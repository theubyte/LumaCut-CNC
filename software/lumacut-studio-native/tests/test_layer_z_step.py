"""Fokus-Absenkung je Durchgang (Layer.z_step) im Modell und im G-Code."""

import pytest

from lumacut_canvas.export import JobLayer
from lumacut_canvas.gcode import document_to_gcode, layers_to_gcode
from lumacut_canvas.model import Document, Geometry, Layer, Shape


def test_z_step_roundtrip_and_clamp():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, z_step=5.0)
    assert doc.layer(lid).z_step == 2.0  # Z_STEP_RANGE
    doc.update_layer(lid, z_step=0.4567)
    assert doc.layer(lid).z_step == 0.457
    data = doc.layer(lid).to_dict()
    assert data["z_step"] == 0.457
    assert Layer.from_dict(data).z_step == 0.457
    old = dict(data)
    old.pop("z_step")
    assert Layer.from_dict(old).z_step == 0.0  # alte Dateien


def test_gcode_steps_focus_down_between_passes_and_restores(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=100, speed=200, passes=3, z_step=0.8)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    lines = document_to_gcode(doc).splitlines()
    i1, i2, i3 = (lines.index(f"; PASS {n} OF 3") for n in (1, 2, 3))
    first_g1 = next(i for i, l in enumerate(lines) if l.startswith("G1"))
    assert i1 < first_g1  # vor dem ersten Schnitt kein Z (Pi fokussiert dort automatisch)
    assert not any(l.startswith("G0 Z") for l in lines[:i1])
    assert lines[i2 - 3:i2] == ["G91", "G0 Z-0.800 F600", "G90"]
    assert lines[i3 - 3:i3] == ["G91", "G0 Z-0.800 F600", "G90"]
    assert ["G91", "G0 Z1.600 F600", "G90"] == lines[-5:-2]
    assert lines[-2:] == ["M5 I", "M400"]
    assert all(len(l) <= 96 for l in lines)


def test_gcode_rejects_too_large_focus_drop():
    layer = JobLayer("a", "a", 100, 200, 5, [[(40.0, 40.0), (50.0, 40.0)]], z_step_mm=1.0)
    with pytest.raises(ValueError, match="Fokus-Absenkung"):
        layers_to_gcode([layer])  # 4 × 1 mm > 3 mm


def test_zero_z_step_emits_no_z(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, passes=3)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    assert " Z" not in document_to_gcode(doc)
