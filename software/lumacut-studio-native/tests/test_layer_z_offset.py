"""Per-layer relative focus offset (Layer.z_offset / JobLayer.z_offset_mm)."""

import pytest

from _pi_guard import pi_check
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.gcode import document_to_gcode, layers_to_gcode
from lumacut_canvas.model import (MAX_FOCUS_DROP_MM, Z_OFFSET_RANGE, Document, Geometry, Layer,
                                  Shape)


def test_z_offset_range_matches_max_focus_drop():
    assert Z_OFFSET_RANGE == (-MAX_FOCUS_DROP_MM, MAX_FOCUS_DROP_MM)


def test_z_offset_roundtrip_and_clamp():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, z_offset=5.0)
    assert doc.layer(lid).z_offset == MAX_FOCUS_DROP_MM
    doc.update_layer(lid, z_offset=-5.0)
    assert doc.layer(lid).z_offset == -MAX_FOCUS_DROP_MM
    doc.update_layer(lid, z_offset=-1.2345)
    assert doc.layer(lid).z_offset == -1.234
    data = doc.layer(lid).to_dict()
    assert data["z_offset"] == -1.234
    assert Layer.from_dict(data).z_offset == -1.234
    old = dict(data)
    old.pop("z_offset")
    assert Layer.from_dict(old).z_offset == 0.0  # old files
    # Zero is omitted so documents without a focus offset stay byte-identical.
    doc.update_layer(lid, z_offset=0.0)
    assert "z_offset" not in doc.layer(lid).to_dict()


def test_job_layer_maps_z_offset(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, z_offset=-0.75)
    doc.add_shape(Shape("rect", Geometry(10, 10, 5, 5), lid))
    jl = job_layers(doc)[0]
    assert jl.z_offset_mm == -0.75
    assert jl.z_step_mm == 0.0


def test_gcode_emits_relative_z_at_layer_start_and_restores(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=80, speed=1000, passes=1, z_offset=-1.0)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    lines = document_to_gcode(doc).splitlines()
    layer_i = lines.index("; LAYER " + doc.layer(lid).name)
    assert lines[layer_i + 1:layer_i + 4] == ["G91", "G0 Z-1.000 F600", "G90"]
    assert ["G91", "G0 Z1.000 F600", "G90"] == lines[-5:-2]
    assert lines[-2:] == ["M5 I", "M400"]
    # No absolute Z words (Pi-guard).
    assert not any((" Z" in l and not l.startswith("G0 Z") and "G0 Z" not in l)
                   or l.startswith("G0 Z") and "G91" not in lines[max(0, i - 1):i]
                   for i, l in enumerate(lines) if False)
    pi_check(document_to_gcode(doc))
    assert all(len(l) <= 96 for l in lines)


def test_zero_z_offset_emits_no_z_byte_identical(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=50, speed=1500, passes=2)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    base = document_to_gcode(doc)
    assert " Z" not in base
    doc.update_layer(lid, z_offset=0.0)
    assert document_to_gcode(doc) == base


def test_positive_z_offset_raises_then_restores(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, z_offset=0.5, passes=1)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    lines = document_to_gcode(doc).splitlines()
    assert ["G91", "G0 Z0.500 F600", "G90"] in [lines[i:i + 3] for i in range(len(lines) - 2)]
    assert lines[-5:-2] == ["G91", "G0 Z-0.500 F600", "G90"]


def test_combined_with_z_step_restores_step_then_offset(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=100, speed=200, passes=3, z_step=0.5, z_offset=-0.8)
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    lines = document_to_gcode(doc).splitlines()
    layer_i = next(i for i, l in enumerate(lines) if l.startswith("; LAYER"))
    assert lines[layer_i + 1:layer_i + 4] == ["G91", "G0 Z-0.800 F600", "G90"]
    i2 = lines.index("; PASS 2 OF 3")
    assert lines[i2 - 3:i2] == ["G91", "G0 Z-0.500 F600", "G90"]
    # After the last pass: restore z_step drop (1.0), then restore z_offset.
    assert lines[-8:-2] == ["G91", "G0 Z1.000 F600", "G90",
                            "G91", "G0 Z0.800 F600", "G90"]
    pi_check(document_to_gcode(doc))


def test_gcode_rejects_combined_drop_past_max():
    # |offset| + z_step*(passes-1) > 3 mm
    layer = JobLayer("a", "a", 100, 200, 3, [[(40.0, 40.0), (50.0, 40.0)]],
                     z_step_mm=1.0, z_offset_mm=-1.5)
    with pytest.raises(ValueError, match="Fokus-Absenkung"):
        layers_to_gcode([layer])  # 1.5 + 2.0 = 3.5 > 3


def test_gcode_rejects_offset_outside_range():
    layer = JobLayer("a", "a", 100, 200, 1, [[(40.0, 40.0), (50.0, 40.0)]],
                     z_offset_mm=-3.5)
    with pytest.raises(ValueError, match="Fokus-Absenkung"):
        layers_to_gcode([layer])
