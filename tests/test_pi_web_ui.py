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
    assert 'id="phaseSteps"' in HTML and "s?.job?.phase" in HTML   # der Pi meldet job.phase
    for phase in ("home", "probe", "focus", "job", "park"):
        assert 'data-phase="%s"' % phase in HTML
    assert 'id="stop"' in HTML
    assert not re.search(r'\$\("stop"\)\.disabled', HTML)
    assert not re.search(r'getElementById\(["\']stop["\']\)\.disabled', HTML)
    # Not-Aus fragt nach (eigener Dialog) und löst dann M112 aus
    assert '$("stop").onclick=estop' in HTML and "M112" in HTML
    body = HTML[HTML.index("async function estop()"):HTML.index('$("stop").onclick=estop')]
    assert "await ask(" in body and 'call("estop")' in body


def test_light_brightness_effects_and_material_editing():
    for el in ("lightRange", "lightFx", "lightNote", "materialEdit", "materialNew", "materialDelete", "matDialog"):
        assert 'id="%s"' % el in HTML
    assert 'call("light",{brightness:' in HTML and 'call("light",{effects:' in HTML
    assert 'method:"PUT",json:data' in HTML and 'method:"POST",json:data' in HTML and 'method:"DELETE"' in HTML
    assert "base_revision" in HTML


def test_single_main_start_button_runs_autorun():
    assert re.search(r'<button class="btn primary lg block" data-action="autorun" data-motion type="button">.*?Auftrag starten</button>', HTML)
    assert len(re.findall(r'<button[^>]*data-action="autorun"', HTML)) == 1
    assert "Motivmitte" not in HTML   # der Pi tastet ein Raster ab


def test_material_choice_is_shared_on_the_pi():
    # Das gewählte Material liegt im Arbeitsstand des Pi (gilt für alle Geräte),
    # nicht nur im Browser; ohne Material startet kein Auftrag.
    assert 'api("/api/workspace",{method:"PUT",json:{material:{name,thickness_mm:t},base_revision:wsRev' in HTML
    assert "e.status===409" in HTML
    assert 'id="materialMissing"' in HTML


def test_new_pages_and_settings():
    for page in ("steuerung", "auftraege", "material", "kamera", "einstellungen", "system"):
        assert 'data-page="%s"' % page in HTML and 'data-nav="%s"' % page in HTML
    for name in ("machine_name", "exhaust_auto", "exhaust_after_s", "thickness_tolerance_mm", "line_laser_gpio"):
        assert name in HTML
    assert 'op:"report",cmd' in HTML and 'href="/api/backup"' in HTML
    assert 'call("motion_limits"' in HTML and 'call("origin_set"' in HTML
    assert 'api("/api/camera/settings",{method:"PUT",json:body})' in HTML


def test_bed_click_menu_only_sends_laser_off_actions():
    menu = HTML[HTML.index("function bedMenu(ev)"):HTML.index('document.addEventListener("pointerdown"')]
    ops = set(re.findall(r'call\("([a-z_]+)"', menu))
    assert ops == {"moveto", "probe", "origin_set"}
    assert "!free||!homed" in menu


def test_scan_image_lies_outside_the_mirrored_group():
    assert HTML.index('<image id="bedScan"') < HTML.index('<g id="bedFlip"')


def test_light_and_dark_theme():
    assert "@media (prefers-color-scheme:dark)" in HTML and ":root[data-theme=dark]" in HTML
    assert 'localStorage.getItem("lumacut.theme")' in HTML


def test_android_app_tab():
    for el in ("appPanel", "appVersion", "appCheck", "appDownload"):
        assert 'id="%s"' % el in HTML
    assert 'api("/api/app/android")' in HTML and 'op:"app_update_check"' in HTML
    assert 'href="/api/app/android.apk"' in HTML
