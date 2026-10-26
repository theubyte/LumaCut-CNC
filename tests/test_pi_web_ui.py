"""Statische Prüfungen der Pi-Weboberfläche (pi400/marlin/index.html).

Nullpunkt-Konvention: X0/Y0 oben rechts an den Endschaltern, +X fährt nach links,
+Y nach unten zur Tür. API-Werte bleiben rohe Maschinen-mm.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "pi400" / "marlin" / "index.html").read_text(encoding="utf-8")


def test_bed_is_mirrored_in_x_only_with_unmirrored_labels():
    assert '"translate("+W+",0) scale(-1,1)"' in HTML
    assert "scale(1,-1)" not in HTML
    flip = HTML[HTML.index('<g id="bedFlip"'):HTML.index('<g id="bedLabels"')]
    assert "<text" not in flip, "Texte im gespiegelten Bereich würden gespiegelt"
    assert '"0/0"' in HTML and "+X ←" in HTML and "+Y ↓" in HTML


def test_jog_cross_matches_origin_top_right():
    buttons = re.findall(r'<button data-axis="([XY])" data-direction="(-?1)"[^>]*>([XY]) ([+−])', HTML)
    order = [(a, int(d), sign) for a, d, _, sign in buttons]
    # Reihenfolge im Raster: oben, links, rechts, unten
    assert order == [("Y", -1, "−"), ("X", 1, "+"), ("X", -1, "−"), ("Y", 1, "+")]


def test_keyboard_mapping():
    assert 'ArrowLeft:["X",1],ArrowRight:["X",-1],ArrowUp:["Y",-1],ArrowDown:["Y",1]' in HTML


def test_material_ui_uses_real_api_only():
    assert 'api("/api/materials")' in HTML
    for el in ("materialSection", "materialName", "materialThickness", "materialProcess",
               "materialSettings", "materialUnavailable", "materialCompare"):
        assert 'id="%s"' % el in HTML
    assert 'includes("materials")' in HTML  # features-Prüfung für ältere Pis
    # Material wird nicht per erfundenem Endpunkt auf Aufträge angewendet
    assert "material_id" not in HTML
    assert not re.search(r'/api/(jobs|queue)[^"]*material', HTML)
    assert "/api/jobs/\"+encodeURIComponent(name)+\"/content" in HTML


def test_phase_display_and_estop_never_disabled():
    assert 'id="phaseSteps"' in HTML and "s?.phase" in HTML
    for phase in ("home", "probe", "focus", "job", "park"):
        assert 'data-phase="%s"' % phase in HTML
    assert 'id="stop"' in HTML
    assert not re.search(r'\$\("stop"\)\.disabled', HTML)
    assert not re.search(r'getElementById\(["\']stop["\']\)\.disabled', HTML)
    assert "confirm(" in HTML and "M112" in HTML
