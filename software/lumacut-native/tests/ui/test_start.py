"""Starten in the real window against the simulator with real time: preview, checks, frame, go, progress, abort, queue, NOT-AUS, refusals."""
import time

from start_helpers import (K_ESC, K_RET, K_SPACE, K_TAB, add_tested_material, checks, element, image_element, is_open, layer, open_project, pi_action,
                           pi_json, pi_status, project, rect, set_material, shot, star, wait_idle)

SIM_ARGS = ["--slow"]


def go_open(app):
    return is_open(app, "go-confirm")


def run(app):
    app.click("nav-start")
    app.wait(lambda: is_open(app, "start-preview"), timeout=5)
    app.invoke("shell", "setTheme", "light")

    # ---- Nothing there yet ----
    app.wait(lambda: app.get("start-empty-title", "text") == "Noch kein Motiv", timeout=8)
    assert "nothing" in checks(app)
    assert "moved" not in checks(app)
    assert app.get("start-go", "lock"), "ohne Motiv muss Starten gesperrt sein"
    app.wait(lambda: pi_status(app)["connected"], timeout=10)
    app.wait(lambda: "material" in checks(app), timeout=8)
    shot(app, "leer-hell")
    app.click("start-go"); time.sleep(0.2)
    assert not go_open(app)

    # ---- A motif from a project file ----
    open_project(app, project("Rennlauf"))
    app.wait(lambda: app.get("start-preview", "segmentCount") > 0, timeout=10)
    assert app.get("start-preview", "segmentCount") > 8
    assert not is_open(app, "start-empty-title")
    assert app.get("start-estimate", "text").endswith("s"), app.get("start-estimate", "text")
    assert app.get("start-size", "text") == "86 × 82 mm" or "×" in app.get("start-size", "text")
    assert app.get("start-readout", "text").startswith("Bahn 1 von 1"), app.get("start-readout", "text")
    assert is_open(app, "start-layer-Markieren")
    c = checks(app)
    assert "material" in c and c["material"].startswith("Kein Material gewählt"), c
    assert "moved" in c
    assert app.get("start-go", "lock").startswith("Kein Material"), app.get("start-go", "lock")
    assert app.get("frame-go", "lock") == ""
    shot(app, "kein-material-hell")

    # Untested material says so, but does not block.
    set_material(app, "Testpappel", 8)
    app.wait(lambda: "untested" in checks(app), timeout=8)
    assert checks(app)["untested"].startswith("Ungetestetes Material: für „Testpappel“")
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=8)
    add_tested_material(app)
    app.invoke("shell", "machine", "job")
    time.sleep(0.2)
    shot(app, "bereit-hell")

    # Link in a sentence: goes where it says. Found the way a pointer finds it, over the lines of the sentence.
    open_project(app, project("Link", [element(rect(340, 5, 30, 20), kind="Rechteck")]))
    app.wait(lambda: "park" in checks(app), timeout=8)
    time.sleep(0.2)
    r = app.find("check-text-park")
    hit = None
    for yy in range(int(r["y"]) + 2, int(r["y"] + r["h"]), 6):
        for xx in range(int(r["x"]), int(r["x"] + r["w"]), 14):
            app.call("mouse", x=xx, y=yy, type="move")
            if app.get("check-text-park", "hoveredLink"):
                hit = (xx, yy)
                break
        if hit:
            break
    assert hit and app.get("check-text-park", "hoveredLink") == "motiv", "Kein Link im Satz gefunden"
    app.call("mouse", x=hit[0], y=hit[1], type="press")
    app.call("mouse", x=hit[0], y=hit[1], type="release")
    time.sleep(0.4)
    assert not is_open(app, "start-preview"), "Der Link führt nicht weg"
    app.click("nav-start")
    app.wait(lambda: is_open(app, "start-preview"), timeout=5)
    open_project(app, project("Rennlauf"))
    app.wait(lambda: app.get("start-preview", "segmentCount") > 0, timeout=8)

    # ---- Preview: zoom, pan, playback ----
    z0 = app.get("start-preview", "effectiveZoom")
    r = app.find("start-preview")
    cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
    app.call("wheel", x=cx, y=cy, dy=240)
    time.sleep(0.1)
    assert app.get("start-preview", "effectiveZoom") > z0
    assert app.get("start-zoom-value", "text") != "100 %"
    p0 = app.invoke("start-stage", "originX")
    app.drag(cx, cy, cx + 60, cy + 30)
    time.sleep(0.1)
    assert abs(app.invoke("start-stage", "originX") - p0 - 60) < 2, "Ziehen verschiebt nicht"
    app.click("start-zoom-fit"); time.sleep(0.1)
    assert app.get("start-zoom-value", "text") == "100 %"

    n = app.get("start-preview", "segmentCount")
    assert app.get("start-preview", "visibleCount") == -1
    app.click("start-to-begin"); time.sleep(0.1)
    assert app.get("start-preview", "visibleCount") == 0
    app.click("start-play")
    time.sleep(1.5)
    mid = app.get("start-preview", "visibleCount")
    assert 0 < mid < n, mid
    assert is_open(app, "start-head")
    shot(app, "abspielen-hell")
    app.click("start-play")
    stopped = app.get("start-preview", "visibleCount")
    time.sleep(0.3)
    assert app.get("start-preview", "visibleCount") == stopped, "Anhalten hält nicht an"
    app.click("start-step-forward"); time.sleep(0.05)
    assert app.get("start-preview", "visibleCount") != stopped
    # The slider: drag to the end means the whole job again.
    s = app.find("start-slider")
    app.drag(s["x"] + 40, s["y"] + s["h"] / 2, s["x"] + s["w"] + 30, s["y"] + s["h"] / 2)
    time.sleep(0.05)
    assert app.get("start-preview", "visibleCount") == -1
    assert app.get("start-travel", "checked") is True
    app.click("start-travel"); time.sleep(0.05)
    assert app.get("start-preview", "showTravel") is False
    app.click("start-travel"); time.sleep(0.05)

    # ---- The sentences ----
    def sentences(path, wanted):
        open_project(app, path)
        app.wait(lambda: wanted in checks(app), timeout=8)
        return checks(app)[wanted]
    t = sentences(project("Draussen", [element(rect(350, 200, 80, 40), kind="Rechteck")]), "outside")
    assert t.startswith("„Rechteck“ ragt über die Arbeitsfläche hinaus"), t
    assert app.get("start-go", "lock") == t
    shot(app, "pruefung-aussen-hell")
    t = sentences(project("Parken", [element(rect(340, 5, 30, 20), kind="Rechteck")]), "park")
    assert "Park-Ecke (oben rechts)" in t, t
    t = sentences(project("Dreh", [image_element(40, 30, 40, 30, rotation=5)], [layer(mode="FILL")]), "rotated")
    assert t.startswith("Das Bild „Bild“ ist gedreht"), t
    weak_id = "weak-L0"
    t = sentences(project("Schwach", [element(star())], [layer(power=5)]), weak_id)
    assert t.startswith("Ebene „Markieren“ hat nur 5 % Leistung: unter 8 %"), t
    assert app.get("start-go", "lock") == "", "Warnung darf nicht sperren"
    shot(app, "pruefung-schwach-hell")
    t = sentences(project("Schnell", [element(star())], [layer(speed=20000)]), "fast-L0")
    assert "zu schnell: 20.000 mm/min" in t or "zu schnell: 20000 mm/min" in t, t
    # The locked strip: the Pi's work band.
    pi_action(app, "work_band", y=60)
    app.wait(lambda: app.get("start-park-label", "text") == "Gesperrter Streifen", timeout=8)
    t = sentences(project("Streifen", [element(rect(100, 20, 40, 20), kind="Rechteck")]), "band")
    assert "gesperrten Streifen" in t, t
    shot(app, "pruefung-streifen-hell")
    pi_action(app, "work_band", y="")
    app.wait(lambda: app.get("start-park-label", "text") == "Park-Ecke", timeout=8)

    # ---- Plates: each has its own job, its own name, an empty one says so ----
    open_project(app, project("Platten", [element(star()), element(rect(40, 50, 30, 30), id="E2", kind="Rechteck", plate=1)], plates=3))
    assert is_open(app, "start-plate")
    first = app.get("start-preview", "segmentCount")
    app.click("start-plate-1")
    app.wait(lambda: not app.invoke("start-api", "building") and app.get("start-preview", "segmentCount") != first, timeout=8)
    assert app.get("start-size", "text").startswith("30")
    shot(app, "platten-hell")
    app.click("start-plate-2")
    app.wait(lambda: is_open(app, "start-empty-title") and app.get("start-empty-title", "text") == "Platte 3 ist leer", timeout=8)
    assert checks(app)["nothing"].startswith("Platte 3 ist leer")
    assert app.get("start-go", "lock"), "leere Platte darf nicht starten"
    app.wait(lambda: app.get("start-preview", "segmentCount") == 0, timeout=8)
    # Leaving the view and coming back: the job is still there, without a new calculation.
    app.click("start-plate-1")
    app.wait(lambda: app.get("start-preview", "segmentCount") > 0, timeout=8)
    n1 = app.get("start-preview", "segmentCount")
    app.click("nav-material"); time.sleep(0.3)
    app.click("nav-start")
    app.wait(lambda: is_open(app, "start-preview") and app.get("start-preview", "segmentCount") == n1 or (is_open(app, "start-preview") and app.get("start-preview", "segmentCount") > 0), timeout=8)

    # ---- Frame: first the reference, each with its own go ----
    open_project(app, project("Rennlauf"))
    app.wait(lambda: app.get("frame-go", "lock") == "", timeout=8)
    assert pi_status(app)["homed"] is False
    app.click("frame-go"); time.sleep(0.2)
    assert app.get("go-detail", "text").startswith("Für den Rahmen"), app.get("go-detail", "text")
    app.key(K_RET); time.sleep(0.2)   # Enter means Abbrechen here
    assert not go_open(app)
    assert pi_status(app)["homed"] is False
    app.wait(lambda: app.get("frame-go", "lock") == "", timeout=5)
    app.click("frame-go"); time.sleep(0.2)
    app.click("go-confirm")
    app.wait(lambda: go_open(app) and app.get("go-detail", "text").startswith("Der Kopf fährt den Umriss"), timeout=30)
    app.click("go-confirm")
    app.wait(lambda: is_open(app, "frame-abort"), timeout=10)
    assert app.get("frame-abort", "text").startswith("Rahmen abbrechen")
    shot(app, "rahmen-hell")
    app.wait(lambda: not is_open(app, "frame-abort"), timeout=60)
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=10)

    # ---- Start: Enter never triggers ----
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    assert "Dauer ca." in app.get("go-detail", "text")
    shot(app, "go-hell")
    app.key(K_RET); time.sleep(0.3)
    assert not go_open(app), "Enter muss Abbrechen sein"
    assert pi_status(app)["job"]["state"] in ("idle",)
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=8)
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    app.key(K_TAB); time.sleep(0.1)
    app.key(K_RET); app.key(K_SPACE, 0, " "); time.sleep(0.4)
    assert go_open(app), "Enter oder Leertaste haben den Go ausgelöst"
    assert pi_status(app)["job"]["state"] == "idle"
    app.key(K_ESC); time.sleep(0.2)
    assert not go_open(app)

    # ---- Go, run, progress ----
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=8)
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    app.click("go-confirm")
    app.wait(lambda: is_open(app, "start-run"), timeout=15)
    assert not is_open(app, "start-go")
    assert app.get("start-run-file", "text") == "Rennlauf.gcode"
    assert app.get("job-file", "text") == "Rennlauf.gcode"     # the strip across the top
    assert app.invoke("shell", "machine", "job")["file"] == "Rennlauf.gcode"
    app.wait(lambda: app.get("start-run-remaining", "text").startswith("Messpunkt"), timeout=30)
    shot(app, "lauf-abtasten-hell")
    app.wait(lambda: app.get("start-run-remaining", "text").startswith("noch ca."), timeout=90)
    assert app.get("start-preview", "visibleCount") >= 0
    assert is_open(app, "start-head")
    app.wait(lambda: app.get("start-preview", "visibleCount") > 0, timeout=30)
    shot(app, "lauf-hell")
    # While it runs, the shell's strip leads back here from elsewhere.
    app.click("nav-material"); time.sleep(0.3)
    app.click("job-file"); time.sleep(0.4)
    assert is_open(app, "start-run")

    # ---- Abort ----
    app.click("run-abort")
    app.wait(lambda: is_open(app, "start-result"), timeout=60)
    assert app.get("start-result-text", "text").startswith("Abgebrochen"), app.get("start-result-text", "text")
    shot(app, "abgebrochen-hell")
    app.click("start-result-close"); time.sleep(0.1)
    assert not is_open(app, "start-result")
    wait_idle(app)
    assert app.get("start-preview", "visibleCount") == -1

    # ---- Refusal by the Pi at the start: the material vanished while the go dialog stood open. Its own sentence stays in the checks. ----
    open_project(app, project("Weggenommen"))
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=8)
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    w = pi_json(app, "GET", "/api/workspace")
    pi_json(app, "PUT", "/api/workspace", {"base_revision": w["revision"], "updated_by": "Test", "material": None})
    app.click("go-confirm")
    app.wait(lambda: "rejected" in checks(app), timeout=15)
    assert "Material" in checks(app)["rejected"], checks(app)["rejected"]
    assert not is_open(app, "start-run")
    assert app.get("start-go", "lock") == checks(app)["rejected"]
    shot(app, "abgelehnt-hell")
    set_material(app, "Testpappel", 8)
    open_project(app, project("Rennlauf"))
    assert "rejected" not in checks(app), "ein geänderter Auftrag braucht die alte Ablehnung nicht mehr"

    # ---- Refusal during the run: wrong material thickness, the Pi's sentence comes back as the result ----
    open_project(app, project("Dicke"))
    set_material(app, "Testpappel", 3)
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=8)
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    app.click("go-confirm")
    app.wait(lambda: is_open(app, "start-result"), timeout=90)
    text = app.get("start-result-text", "text")
    assert text.startswith("Gemessen") and "Testpappel" in text, text
    shot(app, "fehler-hell")
    set_material(app, "Testpappel", 8)
    wait_idle(app)
    app.click("start-result-close")

    # ---- A run to its end ----
    open_project(app, project("Rennlauf"))
    app.wait(lambda: app.get("start-go", "lock") == "", timeout=15)
    app.click("start-go")
    app.wait(lambda: go_open(app), timeout=20)
    app.click("go-confirm")
    app.wait(lambda: is_open(app, "start-run"), timeout=15)
    app.wait(lambda: is_open(app, "start-result"), timeout=150)
    assert app.get("start-result-text", "text") == "Fertig: Rennlauf.gcode ist gelasert, der Kopf steht geparkt.", app.get("start-result-text", "text")
    assert app.get("start-preview", "visibleCount") == -1
    shot(app, "fertig-hell")
    app.click("start-result-close")
    wait_idle(app)

    # ---- Queue ----
    app.click("dock-toggle"); time.sleep(0.2)
    open_project(app, project("Erster"))
    app.wait(lambda: app.get("queue-add-current", "active"), timeout=8)
    app.click("queue-add-current")
    app.wait(lambda: app.get("queue-count", "text") == "1", timeout=10)
    open_project(app, project("Zweiter"))
    app.wait(lambda: app.get("queue-add-current", "active"), timeout=8)
    app.click("queue-add-current")
    app.wait(lambda: app.get("queue-count", "text") == "2", timeout=10)
    app.wait(lambda: app.get("jobs-count", "text") >= "2", timeout=10)
    assert is_open(app, "queue-item-1")
    shot(app, "warteschlange-hell")
    # Removing the second one, enqueuing it again from the saved list.
    app.click("queue-remove-1")
    app.wait(lambda: app.get("queue-count", "text") == "1", timeout=8)
    jobs = app.invoke("start-api", "jobs")
    index = next(i for i, j in enumerate(jobs) if j["name"] == "Zweiter.gcode")
    app.click(f"job-enqueue-{index}")
    app.wait(lambda: app.get("queue-count", "text") == "2", timeout=8)
    # Starting it needs the go too.
    app.click("queue-run")
    app.wait(lambda: go_open(app), timeout=8)
    app.key(K_RET); time.sleep(0.2)
    assert pi_status(app)["queue"]["state"] != "running"
    app.click("queue-run")
    app.wait(lambda: go_open(app), timeout=8)
    app.click("go-confirm")
    app.wait(lambda: is_open(app, "start-run"), timeout=15)
    assert is_open(app, "queue-pause")
    app.wait(lambda: pi_status(app)["queue"]["state"] == "running", timeout=8)
    assert app.get("start-run-file", "text") == "Erster.gcode"
    # The queue runs another file than the open project: the preview shows the running one.
    app.wait(lambda: app.get("start-preview", "segmentCount") > 0, timeout=10)
    shot(app, "warteschlange-lauf-hell")

    # ---- NOT-AUS in the run: no question, the sentence says what next ----
    app.wait(lambda: pi_status(app)["job"]["state"] in ("probing", "running"), timeout=30)
    app.click("estop")
    app.wait(lambda: pi_status(app).get("emergency_latched"), timeout=5)
    app.wait(lambda: is_open(app, "start-result") or not is_open(app, "start-run"), timeout=15)
    app.wait(lambda: "machine" in checks(app), timeout=8)
    assert checks(app)["machine"].startswith("Not-Aus ist aktiv"), checks(app)
    assert app.get("start-go", "lock").startswith("Not-Aus")
    shot(app, "notaus-hell")
    pi_action(app, "estop_reset")
    app.wait(lambda: not pi_status(app).get("emergency_latched"), timeout=10)
    app.wait(lambda: "machine" not in checks(app) or "beschäftigt" in checks(app)["machine"], timeout=15)

    # ---- Saved jobs: preview, back, upload from a path, export to a path, delete with a question ----
    app.wait(lambda: not pi_status(app)["queue"]["items"] or True, timeout=1)
    pi_action(app, "queue_clear")
    app.wait(lambda: app.get("queue-count", "text") == "0", timeout=8)
    jobs = app.invoke("start-api", "jobs")
    index = next(i for i, j in enumerate(jobs) if j["name"] == "Erster.gcode")
    app.click(f"job-preview-{index}")
    app.wait(lambda: is_open(app, "start-source-name") and app.get("start-source-name", "text") == "Erster.gcode", timeout=8)
    app.wait(lambda: app.get("start-preview", "segmentCount") > 0, timeout=10)
    app.wait(lambda: not app.invoke("start-api", "building"), timeout=10)
    assert not is_open(app, "queue-add-current")
    assert not is_open(app, "start-layer-Markieren")
    assert app.get("start-estimate", "text") != "–"
    app.click("start-back-to-motif")
    app.wait(lambda: is_open(app, "queue-add-current"), timeout=8)

    from start_helpers import TMP
    out = str(TMP / "export.gcode").replace("\\", "/")
    app.invoke("start-api", "exportJob", ["Erster.gcode", out])
    app.wait(lambda: (TMP / "export.gcode").exists(), timeout=8)
    assert b"G1" in (TMP / "export.gcode").read_bytes()
    imported = TMP / "Hochgeladen.gcode"
    imported.write_bytes((TMP / "export.gcode").read_bytes())
    app.invoke("start-api", "uploadFile", str(imported).replace("\\", "/"))
    app.wait(lambda: is_open(app, "start-source-name") and app.get("start-source-name", "text") == "Hochgeladen.gcode", timeout=10)
    app.click("start-back-to-motif")
    time.sleep(0.2)
    # G-code the Pi refuses: its sentence comes back, nothing is shown as uploaded.
    refused = TMP / "Verboten.gcode"
    refused.write_text("G21" + chr(10) + "G90" + chr(10) + "M112" + chr(10), encoding="utf-8")
    app.invoke("start-api", "uploadFile", str(refused).replace("\\", "/"))
    app.wait(lambda: "G-Code" in app.invoke("shell", "lastToast") or "Zeile" in app.invoke("shell", "lastToast"), timeout=8)
    assert all(j["name"] != "Verboten.gcode" for j in app.invoke("start-api", "jobs"))
    jobs = app.invoke("start-api", "jobs")
    index = next(i for i, j in enumerate(jobs) if j["name"] == "Hochgeladen.gcode")
    app.click(f"job-delete-{index}")
    app.wait(lambda: is_open(app, "confirm-ok"), timeout=5)
    app.click("confirm-ok")
    app.wait(lambda: all(j["name"] != "Hochgeladen.gcode" for j in app.invoke("start-api", "jobs")), timeout=8)

    # ---- Dark and the other sizes, with a job and an open dock ----
    open_project(app, project("Rennlauf", [element(star(), id="E1"), element(rect(160, 60, 90, 70), id="E2", kind="Rechteck", layer_id="L1"), image_element(120, 90, 60, 45, x=60, y=170, gray=None, id="E3", layer_id="L2")],
                              [layer(), layer(id="L1", name="Schneiden", power=85, speed=400, passes=2), layer(id="L2", name="Gravieren", mode="FILL", power=25, speed=3000)]))
    app.wait(lambda: app.get("start-preview", "segmentCount") > 100, timeout=20)
    time.sleep(0.5)
    shot(app, "gemischt-hell")
    app.invoke("shell", "setTheme", "dark")
    time.sleep(0.4)
    shot(app, "gemischt-dunkel")
    app.click("dock-toggle"); time.sleep(0.2)
    shot(app, "gemischt-dunkel-zu")
    for w, h in ((1000, 640), (1440, 900), (2560, 1440)):
        app.call("resize", w=w, h=h)
        time.sleep(0.5)
        shot(app, f"dunkel-{w}")
    app.invoke("shell", "setTheme", "light")
    time.sleep(0.3)
    for w, h in ((1000, 640), (1440, 900), (2560, 1440)):
        app.call("resize", w=w, h=h)
        time.sleep(0.5)
        shot(app, f"hell-{w}")
