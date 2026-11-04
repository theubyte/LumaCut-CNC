"""Speed display unit mm/min ↔ mm/s (docs/REVIEW_GAP_ANALYSIS_2026-10-25.md §38).

Stored, computed and sent is always mm/min; the layer panel, the image,
material test and scan offset dialogs only convert for display and input.
"""
import pytest
from PySide6.QtWidgets import QTableWidgetItem

from lumacut_canvas import units
from lumacut_canvas.unit_ui import (DisplaySpeedUnits, SpeedSpin, SpeedUnitCombo,
                                    display_speed_units)


@pytest.fixture(autouse=True)
def back_to_mm_min(qapp):
    display_speed_units().set_unit("mm/min")
    yield
    display_speed_units().set_unit("mm/min")


def _doc(speed=1000.0, **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, speed=speed, **layer)
    doc.add_shape(Shape("rect", Geometry(10, 10, 20, 10), lid))
    return doc


def _gcode(doc):
    from lumacut_canvas.gcode import document_to_gcode
    return document_to_gcode(doc)


# --- Qt-free conversion -------------------------------------------------------

def test_conversion_and_formatting():
    assert units.speed_factor("mm/s") == 60 and units.speed_factor("mm/min") == 1
    assert units.speed_to_display(1500, "mm/s") == pytest.approx(25)
    assert units.speed_from_display(25, "mm/s") == 1500
    assert units.format_speed(1500, "mm/s") == "25 mm/s"
    assert units.format_speed(1000, "mm/s") == "16.67 mm/s"
    assert units.format_speed(1, "mm/s", with_unit=False) == "0.02"
    assert units.format_speed(2400, "mm/min") == "2400 mm/min"
    assert units.format_speed(1500.5, "mm/min", with_unit=False) == "1500.5"
    assert units.format_speed(1000, "mm/s", decimals=1) == "16.7 mm/s"
    assert units.format_speed(0, "mm/s") == "0 mm/s"


def test_parsing_comma_and_explicit_unit():
    assert units.parse_speed("16,67", "mm/s") == pytest.approx(1000.2)
    assert units.parse_speed("25", "mm/s") == 1500
    assert units.parse_speed("3000 mm/min", "mm/s") == 3000     # explicit unit wins
    assert units.parse_speed("25mm/s", "mm/min") == 1500
    assert units.parse_speed("25 MM/S", "mm/min") == 1500
    assert units.parse_speed(" 1500 ", "mm/min") == 1500
    assert units.parse_speed("\u221210", "mm/min") == -10        # Unicode minus
    for bad in ("", "schnell", "inf", "nan", "mm/s"):
        with pytest.raises(ValueError):
            units.parse_speed(bad, "mm/s")
    with pytest.raises(ValueError):
        units.check_speed("m/s")
    with pytest.raises(ValueError):
        units.format_speed(1, "in/min")


# --- shared setting -----------------------------------------------------------

def test_display_speed_units_toggle_signal_and_no_settings_in_tests(qapp):
    got = []
    display_speed_units().changed.connect(got.append)
    display_speed_units().toggle()
    display_speed_units().set_unit("mm/s")            # no change, no signal
    display_speed_units().toggle()
    assert got == ["mm/s", "mm/min"]
    display_speed_units().changed.disconnect(got.append)
    with pytest.raises(ValueError):
        display_speed_units().set_unit("km/h")


def test_display_speed_unit_is_stored_in_app_settings(qapp, tmp_path):
    from PySide6.QtCore import QCoreApplication, QSettings
    old_org, old_app = QCoreApplication.organizationName(), QCoreApplication.applicationName()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QCoreApplication.setOrganizationName("LumaCutSpeedTest")
    QCoreApplication.setApplicationName("SpeedUnitTest")
    try:
        a = DisplaySpeedUnits()
        assert a.unit == "mm/min"
        a.set_unit("mm/s")
        assert QSettings().value("canvas/speed_unit") == "mm/s"
        assert DisplaySpeedUnits().unit == "mm/s"           # next start reads it
        QSettings().setValue("canvas/speed_unit", "furlong")
        assert DisplaySpeedUnits().unit == "mm/min"         # unknown value ignored
    finally:
        QCoreApplication.setOrganizationName(old_org)
        QCoreApplication.setApplicationName(old_app)


# --- widgets ------------------------------------------------------------------

def test_speed_spin_value_stays_mm_min(qapp):
    spin = SpeedSpin(1, 6000, 1000)
    assert spin.text() == "1000 mm/min" and spin.value() == 1000
    assert spin.singleStep() == 50
    display_speed_units().set_unit("mm/s")
    assert spin.unit == "mm/s" and spin.text() == "16.67 mm/s" and spin.value() == 1000
    assert spin.singleStep() == 60                    # one arrow step = 1 mm/s
    spin.lineEdit().setText(spin.text())              # unchanged text = unchanged value
    spin.interpretText()
    assert spin.value() == 1000
    spin.lineEdit().setText("20 mm/s")
    spin.interpretText()
    assert spin.value() == 1200 and spin.text() == "20 mm/s"
    spin.lineEdit().setText("schnell mm/s")            # garbage keeps the value
    spin.interpretText()
    assert spin.value() == 1200
    spin.lineEdit().setText("3000 mm/min")            # explicit unit typed in mm/s mode
    spin.interpretText()
    assert spin.value() == 3000 and spin.text() == "50 mm/s"
    spin.stepBy(1)
    assert spin.value() == 3060
    from PySide6.QtGui import QValidator
    assert spin.validate("200 mm/s", 0)[0] == QValidator.Intermediate   # 12000 mm/min > max
    assert spin.validate("100 mm/s", 0)[0] == QValidator.Acceptable
    assert spin.validate("", 0)[0] == QValidator.Intermediate
    display_speed_units().set_unit("mm/min")
    assert spin.text() == "3060 mm/min"


def test_speed_unit_combo_follows_and_sets_the_shared_unit(qapp):
    a, b = SpeedUnitCombo(), SpeedUnitCombo()
    assert a.currentData() == "mm/min"
    b.setCurrentIndex(1)
    b.activated.emit(1)
    assert display_speed_units().unit == "mm/s" and a.currentData() == "mm/s"
    display_speed_units().set_unit("mm/min")
    assert a.currentData() == b.currentData() == "mm/min"


# --- layers panel -------------------------------------------------------------

def test_layers_panel_shows_and_edits_speed_in_mm_s(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary
    doc = _doc(1000.0)
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    layer = doc.active_layer
    assert p.speed.text() == "1000 mm/min"
    assert "1000 mm/min" in layer_summary(layer)
    p.speed_unit.setCurrentIndex(1)
    p.speed_unit.activated.emit(1)
    assert display_speed_units().unit == "mm/s"
    assert p.speed.text() == "16.67 mm/s" and layer.speed == 1000.0
    assert stack.count() == 0                          # switching is not an edit
    assert f"{layer.power:g} % · 16.67 mm/s · 1×" in layer_summary(layer)
    assert layer_summary(layer, "mm/min").count("1000 mm/min") == 1
    row = p.list.itemWidget(p.list.item(0))
    from PySide6.QtWidgets import QLabel
    texts = [w.text() for w in row.findChildren(QLabel)]
    assert any("16.67 mm/s" in t for t in texts), texts    # list row redrawn in mm/s
    p.speed.lineEdit().setText(p.speed.text())         # focus out on the rounded text
    p.speed.interpretText()
    assert layer.speed == 1000.0 and stack.count() == 0
    p.speed.lineEdit().setText("25")
    p.speed.interpretText()
    assert layer.speed == 1500.0 and stack.count() == 1
    stack.undo()
    assert layer.speed == 1000.0 and p.speed.text() == "16.67 mm/s"
    display_speed_units().set_unit("mm/min")
    assert p.speed.text() == "1000 mm/min" and p.speed_unit.currentData() == "mm/min"
    texts = [w.text() for w in p.list.itemWidget(p.list.item(0)).findChildren(QLabel)]
    assert any("1000 mm/min" in t for t in texts)


def test_material_summary_uses_the_speed_unit(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel
    doc = _doc(1500.0, material="MDF", thickness_mm=3.0)
    p = LayersPanel(doc, QUndoStack())
    p.set_material_choice_external(True)
    assert "1500 mm/min" in p.material_summary.text()
    display_speed_units().set_unit("mm/s")
    assert "25 mm/s" in p.material_summary.text()


def test_gcode_is_identical_in_both_display_units(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel
    doc = _doc(1000.0)
    before = _gcode(doc)
    assert "F1000" in before
    p = LayersPanel(doc, QUndoStack())
    display_speed_units().set_unit("mm/s")
    p.refresh()
    assert _gcode(doc) == before
    assert _gcode(_doc(1000.0)) == before


# --- dialogs ------------------------------------------------------------------

def test_image_dialog_speed_in_mm_s_returns_mm_min(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    st = ImageSettings(speed_mm_min=1000.0)
    display_speed_units().set_unit("mm/s")
    dlg = ImageSettingsDialog(st, 10.0, 100)
    assert dlg.speed.text() == "16.67 mm/s" and dlg.speed_unit.currentData() == "mm/s"
    assert dlg.settings() == st.normalized()          # unchanged text = exact value
    dlg.speed.lineEdit().setText("40")
    dlg.speed.interpretText()
    assert dlg.settings().speed_mm_min == 2400.0
    display_speed_units().set_unit("mm/min")
    assert dlg.speed.text() == "2400 mm/min"


def test_material_test_dialog_speeds_in_mm_s(qapp):
    from lumacut_job.material_test import MaterialTestSpec
    from lumacut_job.qt_tools import MaterialTestDialog
    display_speed_units().set_unit("mm/s")
    dlg = MaterialTestDialog(None, MaterialTestSpec(speed_min=600.0, speed_max=3000.0))
    assert dlg.s_min.text() == "10 mm/s" and dlg.s_max.text() == "50 mm/s"
    spec = dlg.spec()
    assert (spec.speed_min, spec.speed_max) == (600.0, 3000.0)
    dlg.s_max.lineEdit().setText("60")
    dlg.s_max.interpretText()
    assert dlg.spec().speed_max == 3600.0


def _table(*rows, enabled=True):
    from lumacut_job.scan_offset import ScanOffsetTable
    return ScanOffsetTable(enabled, list(rows))


def test_scan_offset_dialog_in_mm_s_keeps_exact_values(qapp):
    from lumacut_job.scan_offset_qt import ScanOffsetDialog
    display_speed_units().set_unit("mm/s")
    t = _table((1000, 0.1), (3000, 0.3))
    dlg = ScanOffsetDialog(t)
    assert dlg.grid.horizontalHeaderItem(0).text() == "Geschwindigkeit (mm/s)"
    assert [dlg.grid.item(r, 0).text() for r in range(2)] == ["16.67", "50"]
    assert dlg.probe.text() == "50" and dlg.probe_unit.text() == "mm/s:"
    assert dlg.table().entries == [(1000.0, 0.1), (3000.0, 0.3)]   # not 1000.2
    assert "0,300" in dlg.check_label.text()
    dlg.probe.setText("33,333")                       # ≈ 2000 mm/min → 0,2
    assert "0,200" in dlg.check_label.text()
    dlg.grid.setItem(1, 0, QTableWidgetItem("60"))    # typed in mm/s
    assert dlg.table().entries[-1] == (3600.0, 0.3)
    dlg.add_row()
    assert dlg.grid.item(2, 0).text() == "76.67"       # 3600 + 1000 mm/min
    assert dlg.table().entries[-1] == (4600.0, 0.0)


def test_scan_offset_dialog_switches_unit_live(qapp):
    from lumacut_job.scan_offset_qt import ScanOffsetDialog
    dlg = ScanOffsetDialog(_table((1000, 0.1), (3000, 0.3)))
    assert dlg.grid.horizontalHeaderItem(0).text() == "Geschwindigkeit (mm/min)"
    assert dlg.grid.item(0, 0).text() == "1000" and dlg.probe.text() == "3000"
    dlg.grid.setItem(1, 0, QTableWidgetItem("2500"))  # user edit before the switch
    dlg.speed_unit.setCurrentIndex(1)
    dlg.speed_unit.activated.emit(1)
    assert dlg.grid.horizontalHeaderItem(0).text() == "Geschwindigkeit (mm/s)"
    assert [dlg.grid.item(r, 0).text() for r in range(2)] == ["16.67", "41.67"]
    assert dlg.probe.text() == "50"
    assert dlg.table().entries == [(1000.0, 0.1), (2500.0, 0.3)]
    dlg.grid.setItem(0, 0, QTableWidgetItem("abc"))   # bad cell survives a switch
    display_speed_units().set_unit("mm/min")
    assert dlg.grid.item(0, 0).text() == "abc" and dlg.grid.item(1, 0).text() == "2500"
    assert "Zeile 1" in dlg.error.text()
    dlg.grid.setItem(0, 0, QTableWidgetItem("1000"))
    assert dlg.table().entries == [(1000.0, 0.1), (2500.0, 0.3)]
    assert dlg.probe.text() == "3000"


def test_scan_test_dialog_speeds_in_mm_s_give_identical_gcode(qapp):
    from lumacut_job.scan_offset import ScanTestSpec
    from lumacut_job.scan_offset_qt import ScanTestDialog
    spec = ScanTestSpec(speeds=[1000.0, 2000.0, 3000.0])
    ref = ScanTestDialog(spec).gcode()
    display_speed_units().set_unit("mm/s")
    dlg = ScanTestDialog(spec)
    assert dlg.speeds.text() == "16.67 33.33 50"
    assert dlg.speeds_label.text() == "Geschwindigkeiten (mm/s)"
    assert dlg.spec().speeds == [1000.0, 2000.0, 3000.0] and dlg.gcode() == ref
    dlg.speeds.setText("25; 50")
    assert dlg.spec().speeds == [1500.0, 3000.0]
    display_speed_units().set_unit("mm/min")
    assert dlg.speeds.text() == "1500 3000" and dlg.speeds_label.text().endswith("(mm/min)")
    dlg.speeds.setText("schnell")
    display_speed_units().set_unit("mm/s")              # unparsable text stays
    assert dlg.speeds.text() == "schnell" and "Zahlen" in dlg.info.text()
