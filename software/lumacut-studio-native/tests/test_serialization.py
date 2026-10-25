import json

import pytest

from lumacut_canvas import Document, Geometry, Layer, Shape, load_document, save_document


def sample():
    doc = Document()
    engrave = doc.add_layer(Layer(name="Gravieren", color="#f3a64b", power=20, speed=3000, passes=2))
    doc.add_shape(Shape("rect", Geometry(10, 20, 30, 40), doc.layers[1].id))
    doc.add_shape(Shape("line", Geometry(50, 50, -20, 10), engrave.id))
    doc.add_shape(Shape("text", Geometry(100, 100, 40, 10), engrave.id, text="Grüße"))
    return doc


def test_roundtrip_dict():
    doc = sample()
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert again.to_dict() == doc.to_dict()


def test_save_and_load_file_utf8(tmp_path):
    doc = sample()
    p = save_document(doc, tmp_path / "projekt.lumacut.json")
    assert "Grüße" in p.read_text(encoding="utf-8")
    loaded = load_document(p)
    assert loaded.to_dict() == doc.to_dict()
    assert loaded.layers[0].passes == 2 and loaded.layers[0].speed == 3000


def test_load_rejects_foreign_files():
    with pytest.raises(ValueError):
        Document.from_dict({"format": "svg"})


def test_load_repairs_invalid_content():
    data = sample().to_dict()
    data["objects"][0]["x"] = 1000          # außerhalb
    data["objects"][1]["layer"] = "missing"  # unbekannte Ebene
    data["layers"][0]["power"] = 500
    doc = Document.from_dict(data)
    assert doc.shapes[0].bounds().right <= 360
    assert doc.shapes[1].layer_id in {l.id for l in doc.layers}
    assert doc.layers[0].power == 100
