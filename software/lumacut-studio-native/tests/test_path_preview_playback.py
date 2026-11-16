"""Pfadvorschau wie LightBurns Vorschau: Abspielen mit Tempo, Zeit bis zur Reglerstellung,
Leerfahrten ausblenden („Show traversal moves“) und Schnitte nach Leistung schattieren
(„Shade according to power“) – nur Ansicht, Dokument und G-Code bleiben unverändert."""

from __future__ import annotations

import pytest

from lumacut_canvas.gcode import PWM_MAX
from lumacut_canvas.path_preview import (DEFAULT_PLAY_SPEED, PLAY_SPEEDS, PLAY_TICK_MS,
                                         SHADE_LEVELS, SHADE_MIN_ALPHA, shade_alpha, shade_level)
from lumacut_canvas.toolpath import CUT, RAPID, RAPID_FEED, Toolpath, count_until, parse_gcode

# 10 mm bei F600 (1 s), Leerfahrt 10 mm im Eilgang (F9000: 1/15 s), 20 mm bei F1200 (1 s)
G = """G21
G90
M3 I
; LAYER A
G0 X0 Y0
G1 X10 Y0 F600 S255
G0 X10 Y10
G1 X30 Y10 F1200 S64
M5 I
"""

# Drei Läufe mit verschiedener Leistung, damit die Schattierung drei Stufen zeigt.
G_SHADES = """G21
G90
M3 I
; LAYER Rampe
G0 X0 Y0
G1 X10 Y0 F600 S26
G1 X20 Y0 S128
G1 X30 Y0 S255
G0 X30 Y20
G1 X0 Y20 S255
M5 I
"""


# --- Qt-freie Zeitachse (toolpath) ---------------------------------------------------
def test_move_times_follow_length_and_feed():
    tp = parse_gcode(G)
    assert [m.kind for m in tp.moves] == [CUT, RAPID, CUT]
    assert tp.move_times() == pytest.approx([1.0, 10 / (RAPID_FEED / 60), 1.0])
    assert tp.move_times(rapid_feed=600) == pytest.approx([1.0, 1.0, 1.0])
    # Achsgrenze (mm/s) wie M203: F1200 = 20 mm/s → bei 10 mm/s doppelt so lang
    assert tp.move_times(max_speed=10.0) == pytest.approx([1.0, 1.0, 2.0])


def test_cumulative_times_rise_and_scale_to_the_estimate():
    tp = parse_gcode(G)
    raw = tp.cumulative_times()
    assert raw == sorted(raw) and raw[-1] == pytest.approx(2 + 10 / 150)
    scaled = tp.cumulative_times(total_s=10.0)
    assert scaled[-1] == pytest.approx(10.0)
    # Anteile bleiben: Faktor gleich für jede Bewegung
    assert [b / a for a, b in zip(raw, scaled)] == pytest.approx([10.0 / raw[-1]] * 3)
    # ohne / mit unbrauchbarer Gesamtzeit: unskaliert
    assert tp.cumulative_times(total_s=0) == pytest.approx(raw)
    assert tp.cumulative_times(total_s=None) == pytest.approx(raw)
    assert Toolpath().cumulative_times(5.0) == [] and Toolpath().move_times() == []


def test_count_until():
    cum = [1.0, 1.5, 3.0]
    assert count_until(cum, 0.0) == 0
    assert count_until(cum, 0.99) == 0
    assert count_until(cum, 1.0) == 1          # Bewegung ist mit ihrem Ende fertig
    assert count_until(cum, 2.0) == 2
    assert count_until(cum, 3.0) == 3 and count_until(cum, 99) == 3
    assert count_until([], 1.0) == 0


# --- Leistungs-Schattierung ------------------------------------------------------------
def test_shade_levels_and_alpha():
    assert shade_level(PWM_MAX) == SHADE_LEVELS and shade_alpha(PWM_MAX) == pytest.approx(1.0)
    assert shade_level(0) == 1 and shade_level(-5) == 1     # sichtbar bleibt jeder Schnitt
    assert shade_level(10 * PWM_MAX) == SHADE_LEVELS
    assert shade_alpha(0) > SHADE_MIN_ALPHA
    levels = [shade_level(s) for s in range(0, PWM_MAX + 1)]
    assert levels == sorted(levels) and set(levels) == set(range(1, SHADE_LEVELS + 1))
    assert shade_level(PWM_MAX / 2) == SHADE_LEVELS // 2
    alphas = [shade_alpha(s) for s in (26, 64, 128, 255)]
    assert alphas == sorted(alphas) and len(set(alphas)) == 4


# --- Vorschau im Editor ----------------------------------------------------------------
def _doc(**layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **layer)
    doc.add_shape(Shape("rect", Geometry(20, 20, 30, 20), lid))
    doc.add_shape(Shape("ellipse", Geometry(80, 30, 20, 20), lid))
    doc.add_shape(Shape("rect", Geometry(120, 60, 10, 10), lid))
    return doc


def _editor(doc, gen=None):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor(doc)
    if gen is not None:
        ed.path_preview.set_generator(gen)
    ed.set_path_preview(True)
    return ed


def test_defaults_change_nothing(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = _doc()
    before_doc, before = doc.to_dict(), optimized_document_gcode(doc)
    ed = _editor(doc)
    pv, bar = ed.path_preview, ed.path_preview_bar
    assert pv.show_rapids and not pv.shade_power and not pv.playing
    assert pv.play_speed == DEFAULT_PLAY_SPEED and pv.limit is None
    assert bar.rapids.isChecked() and not bar.shade.isChecked() and not bar.play.isChecked()
    assert bar.speed.currentData() == DEFAULT_PLAY_SPEED
    assert [bar.speed.itemData(i) for i in range(bar.speed.count())] == list(PLAY_SPEEDS)
    assert bar.play.text() == "▶ Abspielen" and bar.play.isEnabled()
    rapid, cuts = pv.paint_lines()
    assert rapid and all(level == 0 for (_src, level) in cuts)
    # Umschalten ist reine Ansicht
    pv.set_show_rapids(False)
    pv.set_shade_power(True)
    pv.play()
    pv.advance(0.5)
    ed.grab()
    assert pv.gcode == before and optimized_document_gcode(doc) == before
    assert doc.to_dict() == before_doc and ed.undo_stack.count() == 0


def test_hide_rapids_keeps_cuts_lengths_and_markers(qapp):
    ed = _editor(_doc())
    pv, bar = ed.path_preview, ed.path_preview_bar
    rapid, cuts = pv.paint_lines()
    n_cut = sum(len(v) for v in cuts.values())
    text, runs = bar.readout.text(), pv.visible_runs()
    assert rapid
    bar.rapids.click()
    assert not pv.show_rapids
    rapid2, cuts2 = pv.paint_lines()
    assert rapid2 == [] and sum(len(v) for v in cuts2.values()) == n_cut
    assert bar.readout.text() == text and pv.visible_runs() == runs   # Länge / Zeit / Nummern bleiben
    ed.grab()
    pv.set_show_rapids(True)
    assert bar.rapids.isChecked() and pv.paint_lines()[0]


def test_shading_follows_power(qapp):
    ed = _editor(_doc(), gen=lambda d: G_SHADES)
    pv, bar = ed.path_preview, ed.path_preview_bar
    src = ("layer", "Rampe")
    assert pv.cut_pens()[src] == [pytest.approx(pv.color(src).alphaF())]
    bar.shade.click()
    assert pv.shade_power
    _rapid, cuts = pv.paint_lines()
    levels = sorted(level for (_s, level) in cuts)
    assert levels == [shade_level(26), shade_level(128), SHADE_LEVELS]
    assert len(cuts[(src, SHADE_LEVELS)]) == 2           # zwei Schnitte mit S255
    alphas = pv.cut_pens()[src]
    assert alphas == sorted(alphas) and alphas[-1] == pytest.approx(1.0) and len(alphas) == 3
    ed.grab()
    pv.set_shade_power(False)
    assert not bar.shade.isChecked()


def test_shading_of_a_ramped_and_a_weak_layer(qapp):
    """Echte Planer-Ausgabe: Rampe = mehrere Stufen in einer Ebene, schwache Ebene = blass."""
    from lumacut_canvas.model import Geometry, Layer, Shape
    doc = _doc(power=100.0, ramp_mm=3.0, ramp_start_power=0.0)
    weak = Layer(name="Schwach", power=20.0)
    doc.add_layer(weak)
    doc.add_shape(Shape("rect", Geometry(150, 20, 20, 20), weak.id))
    ed = _editor(doc)
    pv = ed.path_preview
    pv.set_shade_power(True)
    pens = pv.cut_pens()
    strong = [a for s, a in pens.items() if s[1] != "Schwach"][0]
    weak_a = [a for s, a in pens.items() if s[1] == "Schwach"][0]
    assert len(strong) > 3 and strong[-1] == pytest.approx(1.0)   # Rampe sichtbar
    assert max(weak_a) < 0.4                                      # 20 % ≈ blass


def test_time_axis_matches_the_estimate(qapp):
    ed = _editor(_doc())
    pv = ed.path_preview
    n = len(pv.toolpath.moves)
    times = [pv.time_until(k) for k in range(n + 1)]
    assert times[0] == 0.0 and times == sorted(times)
    assert pv.total_time_s == pytest.approx(pv.estimate.program_time_s, rel=1e-6)
    assert pv.time_until(n + 5) == pytest.approx(pv.total_time_s)
    assert pv.estimate.total_time_s >= pv.total_time_s           # ohne Anfahrt / Parken
    pv.set_limit(n // 2)
    assert "nach ca." in pv.readout()
    pv.set_limit(None)
    assert "nach ca." not in pv.readout()


def test_play_runs_to_the_end_and_stops(qapp):
    ed = _editor(_doc())
    pv, bar = ed.path_preview, ed.path_preview_bar
    total = len(pv.toolpath.moves)
    bar.play.click()                                 # Regler am Ende → von vorn
    assert pv.playing and pv.limit == 0 and bar.play.isChecked()
    assert bar.play.text() == "❚❚ Pause" and bar.slider.value() == 0
    seen = []
    for _ in range(10000):
        pv.advance(PLAY_TICK_MS / 1000)
        seen.append(pv.shown_count())
        if not pv.playing:
            break
    assert not pv.playing and pv.limit is None and seen[-1] == total
    assert seen == sorted(seen) and len(set(seen)) > 2       # läuft schrittweise
    # Dauer passt zum Tempo: Gesamtzeit / 50× ≈ Wanduhrzeit
    expected_ticks = pv.total_time_s / DEFAULT_PLAY_SPEED / (PLAY_TICK_MS / 1000)
    assert len(seen) == pytest.approx(expected_ticks, abs=2)
    assert bar.play.text() == "▶ Abspielen" and not bar.play.isChecked()
    assert bar.slider.value() == total


def test_pause_resume_and_scrub(qapp):
    ed = _editor(_doc())
    pv, bar = ed.path_preview, ed.path_preview_bar
    pv.set_play_speed(1)
    pv.play()
    pv.advance(pv.total_time_s * 0.4)
    k = pv.limit
    assert 0 < k < len(pv.toolpath.moves)
    bar.play.click()                                 # Pause: Regler bleibt stehen
    assert not pv.playing and pv.limit == k
    pv.advance(100)                                  # ohne Abspielen: nichts
    assert pv.limit == k
    pv.play()                                        # weiter ab der Reglerstellung
    assert pv.playing and pv.limit == k
    assert pv._play_t == pytest.approx(pv.time_until(k))
    pv.advance(0.001)
    assert pv.limit >= k
    bar.slider.setValue(2)                           # Ziehen am Regler hält an
    assert not pv.playing and pv.limit == 2
    pv.play()
    pv.rebuild()                                     # Neuberechnung hält an
    assert not pv.playing and pv.limit is None
    pv.play()
    ed.set_path_preview(False)                       # Vorschau aus hält an
    assert not pv.playing and not pv._play_timer.isActive()


def test_speed_changes_progress(qapp):
    doc = _doc()
    slow, fast = _editor(doc).path_preview, _editor(doc).path_preview
    slow.set_play_speed(1)
    fast.set_play_speed(200)
    for pv in (slow, fast):
        pv.play()
        pv.advance(0.2)
    assert slow.shown_count() < fast.shown_count()
    ed = _editor(doc)
    ed.path_preview_bar.speed.setCurrentIndex(PLAY_SPEEDS.index(1000))
    assert ed.path_preview.play_speed == 1000
    ed.path_preview.set_play_speed(10)
    assert ed.path_preview_bar.speed.currentData() == 10


def test_timer_drives_playback(qapp):
    from PySide6.QtTest import QTest
    ed = _editor(_doc())
    pv = ed.path_preview
    pv.set_play_speed(1)
    pv.play()
    assert pv._play_timer.isActive()
    # der Takt führt das Abspielen weiter (großzügige Frist: volle Testläufe unter Last)
    import time
    deadline = time.monotonic() + 5.0
    while pv._play_t <= 0 and time.monotonic() < deadline:
        QTest.qWait(20)
    assert pv._play_t > 0
    assert pv.playing or pv.limit is None
    pv.pause()
    assert not pv._play_timer.isActive()


def test_empty_preview_cannot_play(qapp):
    from lumacut_canvas.model import Document
    ed = _editor(Document())
    pv, bar = ed.path_preview, ed.path_preview_bar
    pv.play()
    assert not pv.playing and pv.total_time_s == 0.0 and pv.time_until(3) == 0.0
    assert not bar.play.isEnabled()
    ed.grab()


def test_estimate_failure_keeps_the_preview(qapp, monkeypatch):
    import lumacut_canvas.path_preview as mod
    monkeypatch.setattr(mod, "_estimate", lambda g: None)
    ed = _editor(_doc())
    pv = ed.path_preview
    assert pv.estimate is None and pv.total_time_s > 0   # einfache Zeiten ohne Schätzung
    pv.play()
    pv.advance(10)
    assert pv.shown_count() > 0


def test_touch_mode_sizes(qapp):
    from lumacut_canvas import theme
    ed = _editor(_doc())
    bar = ed.path_preview_bar
    assert "QSlider#PathScrub::handle:horizontal" in theme.CANVAS_QSS
    ed.set_touch_mode(True, persist=False)
    ed.show()
    qapp.processEvents()
    for w in (bar.play, bar.rapids, bar.shade):
        assert w.sizeHint().height() >= 40
    assert bar.slider.sizeHint().height() >= 40 or bar.slider.minimumHeight() >= 40
    ed.set_touch_mode(False, persist=False)
    ed.close()


def test_main_window_has_the_controls(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    ed = win.canvas
    from lumacut_canvas.model import Geometry, Shape
    lid = ed.document.active_layer_id
    ed.document.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    ed.document.add_shape(Shape("rect", Geometry(50, 0, 40, 40), lid))
    ed.set_path_preview(True)
    pv, bar = ed.path_preview, ed.path_preview_bar
    bar.shade.click()
    bar.rapids.click()
    bar.play.click()
    pv.advance(1000)
    assert pv.shade_power and not pv.show_rapids and pv.limit is None and not pv.playing
    ed.undo_stack.setClean()
    win.close()
