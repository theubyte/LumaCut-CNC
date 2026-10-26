"""Anzeige-Einheit mm/Zoll (docs/REVIEW_GAP_ANALYSIS_2026-10-25.md §9/§10).

Gespeichert und gerechnet wird in mm; nur Anzeige und Eingabe rechnen um.
Der Nullpunkt kommt aus workarea (beide Stellungen werden geprüft).
"""
import pytest

from lumacut_canvas import units, workarea as wa
from lumacut_canvas.model import Geometry, Shape
from lumacut_canvas.unit_ui import LengthSpin, display_units


@pytest.fixture(autouse=True)
def back_to_mm():
    display_units().set_unit("mm")
    yield
    display_units().set_unit("mm")


def test_conversion_and_parsing():
    assert units.to_display(25.4, "in") == pytest.approx(1.0)
    assert units.from_display(2, "in") == pytest.approx(50.8)
    assert units.format_length(12.7, "in") == "0.500 in"
    assert units.format_length(12.345, "mm", with_unit=False) == "12.35"
    assert units.parse_length("1,5", "in") == pytest.approx(38.1)
    assert units.parse_length("10 mm", "in") == pytest.approx(10)   # ausdrückliche Einheit gewinnt
    assert units.parse_length('2"', "mm") == pytest.approx(50.8)
    with pytest.raises(ValueError):
        units.check("cm")


@pytest.mark.parametrize("origin", [False, True])
def test_status_position_uses_workarea_origin(monkeypatch, origin):
    monkeypatch.setattr(wa, "ORIGIN_TOP_RIGHT", origin)
    u, _ = wa.screen_to_user(10, 25.4)
    assert units.format_position(10, 25.4, "mm") == f"X {u:6.1f}  Y {25.4:6.1f} mm"
    assert units.format_position(10, 25.4, "in").endswith(f"{1:7.3f} in")
    assert f"{u / 25.4:.3f}" in units.format_position(10, 25.4, "in")


def test_length_spin_keeps_mm_and_shows_inch(qapp):
    s = LengthSpin(-1000, 1000)
    s.setValue(25.4)
    assert s.text() == "25.40 mm"
    display_units().set_unit("in")
    assert s.text() == "1.000 in" and s.value() == pytest.approx(25.4)
    s.lineEdit().setText("2")
    s.interpretText()
    assert s.value() == pytest.approx(50.8)
    # Unveränderter, gerundeter Anzeigetext darf den Wert nicht verschieben.
    s.setValue(12.3456)
    seen = []
    s.valueChanged.connect(seen.append)
    s.interpretText()
    assert seen == [] and s.value() == pytest.approx(12.3456)


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    ed.resize(900, 700)
    ed.show()
    qapp.processEvents()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


def test_toggle_changes_display_only(editor):
    d = editor.document
    sid = d.add_shape(Shape("rect", Geometry(10, 20, 25.4, 50.8), d.active_layer_id)).id
    editor.set_selection([sid])
    n_undo = editor.undo_stack.count()
    pb = editor.property_bar
    assert pb.w.text() == "25.40 mm"
    a = editor.actions_by_name["unit_toggle"]
    assert a in editor.action_bar.actions() and a.text() == "mm"
    a.trigger()
    assert display_units().unit == "in" and a.text() == "Zoll"
    assert editor.ruler_corner.text() == "in"
    assert pb.w.text() == "1.000 in" and pb.h.text() == "2.000 in"
    assert d.shape(sid).geom.as_tuple() == (10, 20, 25.4, 50.8)   # Dokument unverändert
    assert editor.undo_stack.count() == n_undo                     # Umschalten ist kein Bearbeiten
    pb.w.lineEdit().setText("2")
    pb.w.interpretText()
    assert d.shape(sid).geom.w == pytest.approx(50.8)


def test_ruler_ticks_follow_unit(editor):
    from lumacut_canvas.canvas_view import PX_PER_MM_100
    editor.view.set_zoom(PX_PER_MM_100 * 2)
    ruler = editor.h_ruler
    mm_major = [v for v, _, major in ruler.ticks() if major]
    assert all(float(v).is_integer() for v in mm_major)
    display_units().set_unit("in")
    in_ticks = ruler.ticks()
    in_major = [v for v, _, major in in_ticks if major]
    assert in_major and max(in_major) <= 14.2 + 3          # 360 mm ≈ 14,2 in (+ Rand)
    # Abstand zweier Hauptstriche passt zu Zoll
    (v0, p0, _), (v1, p1, _) = [t for t in in_ticks if t[2]][:2]
    assert abs(p1 - p0) == pytest.approx(abs(v1 - v0) * 25.4 * editor.view.px_per_mm, abs=1.5)
