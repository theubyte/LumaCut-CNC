"""Statische Prüfungen der Pi-Weboberfläche (pi400/marlin/index.html).

Nullpunkt-Konvention: X0/Y0 oben rechts an den Endschaltern, +X fährt nach links,
+Y nach unten zur Tür. API-Werte bleiben rohe Maschinen-mm.
"""
import os
import re
import subprocess
import sys
import tempfile
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


def _section(start, end):
    return HTML[HTML.index(start):HTML.index(end)]


def test_every_motion_and_laser_start_asks_go():
    assert 'const GO_LINE="Hände raus, Deckel zu, Brille – starten?"' in HTML
    go = _section("async function goFor(op)", 'for(const b of $$("[data-action]"))')
    for op in ("home", "probe", "park", "autorun", "start", "queue_run"):
        assert 'case "%s":return askGo(' % op in go
    action = _section('for(const b of $$("[data-action]"))', '$("gotoRun").onclick')
    assert action.index("await goFor(op)") < action.index("call(op,extra,b)")
    frame = _section('$("frameJob").onclick', "/* ================= Materialdatenbank")
    assert frame.index("await askGo(") < frame.index('call("frame"')
    menu = _section("function bedMenu(ev)", 'document.addEventListener("pointerdown"')
    assert menu.count("await askGo(") == 2
    goto = _section('$("gotoRun").onclick', '$("lineLaserBtn").onclick')
    assert goto.count("await askGo(") == 2 and goto.count('call("moveto"') == 2
    assert 'if(!await askGo("Z-Test' in HTML


def test_estop_reachable_inside_dialogs():
    # Modale Dialoge sperren die Kopfzeile: jeder trägt einen eigenen NOT-AUS.
    block = _section('for(const d of $$("dialog")){', "/* ================= API")
    assert "estop()" in block and '"NOT-AUS"' in block


def test_service_ping_and_off_button_stay_safe():
    ping = next(l for l in HTML.splitlines() if "service_laser_ping" in l and "setInterval" in l)
    assert "percent" not in ping, "Der Ping darf nie eine Leistung senden"
    assert not re.search(r'\$\("serviceLaserOff"\)\.disabled', HTML)
    lock = _section("function lockAll()", "// Immer nur eine Statusabfrage")
    assert "#serviceLaserOff" not in lock and "#stop" not in lock
    # Solange der Strahl aus ist, sendet das Ziehen nichts: erst die Abfrage beim Loslassen.
    assert "if(serviceBeam)serviceLaserSend(v)" in HTML
    change = _section('$("serviceLaser").onchange', '$("serviceLaserOff").onclick')
    assert change.index("await ask(") < change.index("serviceLaserSend(")
    assert "Hände raus, Deckel zu, Brille" in change


def test_marlin_only_in_comments():
    # Marlin wird ersetzt: als Name nur noch im Kommentar, M-Codes nur in der Diagnose.
    body = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = "\n".join(l.split("// ")[0] for l in body.splitlines())
    assert "Marlin" not in body and "MARLIN" not in body


def test_pin_info_shows_pa9_at_exp3():
    assert 'id="servicePin">PA9 an EXP3<' in HTML


def test_system_info_endpoint_reads_only():
    source = """
from marlin import web
sent = []
web.machine.command = lambda *a, **k: sent.append(a)
with web.app.test_client() as client:
    r = client.get("/api/system")
assert r.status_code == 200, r.data
data = r.get_json()
for key in ("software_commit", "software_date", "service_uptime_s", "disk_free_bytes",
            "disk_total_bytes", "jobs_bytes", "cpu_temp_c"):
    assert key in data, key
assert data["jobs_bytes"] == 0 and data["disk_free_bytes"] > 0
assert not sent, "Die Abfrage darf die Maschine nicht ansprechen"
"""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, LUMACUT_DATA=tmp, PYTHONPATH=str(root / "pi400"))
        result = subprocess.run([sys.executable, "-c", source], env=env, cwd=root,
                                text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
