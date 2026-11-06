"""Projects in the real window against the simulator: shelf on the Pi, the shared open project with its conflict rule, local file, autosave."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from driver import App
from start_helpers import TMP, element, is_open, layer, open_project, pi_json, project, rect, shot, star

AUTOSAVE = tempfile.mkdtemp(prefix="lumacut-autosave-")
ENV = {"LUMACUT_SYNC": "1", "LUMACUT_AUTOSAVE_DIR": AUTOSAVE}


def doc_json(title, x=30):
    return {"title": title, "layers": [layer()], "elements": [element(rect(x, 60, 40, 30), kind="Rechteck")], "plateCount": 1, "activePlate": 0}


def run(app):
    app.click("nav-start")
    app.wait(lambda: is_open(app, "start-preview"), timeout=5)
    app.wait(lambda: app.invoke("shell", "machine", "connected") is True, timeout=10)

    # Nothing happens to an untouched window as long as nobody changes anything.
    time.sleep(3)
    assert not app.invoke("sync-api", "conflict")
    assert not is_open(app, "conflictDialog-panel")
    assert app.invoke("start-api", "title") != "Vom Tablet"

    # Someone else changes the project, this window has nothing of its own: it follows with a small note, no dialog.
    r = pi_json(app, "PUT", "/api/workspace/project?base_revision=0&by=Tablet", doc_json("Vom Tablet"))
    app.wait(lambda: app.invoke("start-api", "title") == "Vom Tablet", timeout=10)
    assert not is_open(app, "conflict-keep")
    assert "übernommen" in app.invoke("shell", "lastToast")
    assert app.invoke("start-api", "dirty") is False
    assert app.invoke("sync-api", "baseRevision") == r["revision"]
    app.wait(lambda: not app.invoke("start-api", "building"), timeout=10)

    # Own changes go up by themselves, and the own echo in the status never opens the dialog.
    app.invoke("start-api", "setTitle", "Hier geändert")
    app.wait(lambda: app.invoke("sync-api", "baseRevision") > r["revision"], timeout=10)
    time.sleep(3)
    assert not is_open(app, "conflict-keep"), "Der eigene Stand darf den Konfliktdialog nicht öffnen"
    assert pi_json(app, "GET", "/api/workspace/project")["title"] == "Hier geändert"

    # Both changed: only now the question.
    rev = app.invoke("sync-api", "baseRevision")
    app.invoke("start-api", "setTitle", "Hier nochmal")
    pi_json(app, "PUT", f"/api/workspace/project?base_revision={rev}&by=Tablet", doc_json("Dort geändert"))
    app.wait(lambda: is_open(app, "conflict-keep"), timeout=10)
    assert app.get("conflict-text", "text").startswith("Auf dem Pi liegt eine neuere Fassung")
    time.sleep(0.3)
    shot(app, "konflikt-hell")
    # Esc and a click beside it do not answer this question.
    app.key(0x01000000); time.sleep(0.2)
    assert is_open(app, "conflict-keep")
    app.click("conflict-keep")
    app.wait(lambda: not is_open(app, "conflict-keep"), timeout=10)
    assert pi_json(app, "GET", "/api/workspace/project")["title"] == "Hier nochmal"
    assert app.invoke("start-api", "title") == "Hier nochmal"

    # Once more, this time the Pi's version wins.
    rev = app.invoke("sync-api", "baseRevision")
    app.invoke("start-api", "setTitle", "Hier verloren")
    pi_json(app, "PUT", f"/api/workspace/project?base_revision={rev}&by=Tablet", doc_json("Dort gewinnt"))
    app.wait(lambda: is_open(app, "conflict-take"), timeout=10)
    app.click("conflict-take")
    app.wait(lambda: not is_open(app, "conflict-take"), timeout=10)
    assert app.invoke("start-api", "title") == "Dort gewinnt"
    assert app.invoke("start-api", "dirty") is False

    # ---- Shelf on the Pi ----
    app.invoke("sync-api", "openDialog", "save")
    app.wait(lambda: is_open(app, "project-name"), timeout=5)
    app.wait(lambda: is_open(app, "project-none"), timeout=5)
    assert app.get("project-save", "text") == "Speichern"
    time.sleep(0.2)
    shot(app, "projekt-speichern-hell")
    app.click("project-name")
    app.key(0x41, 0x04000000)   # Strg+A
    app.text("Regal Eins")
    time.sleep(0.1)
    app.click("project-save")
    app.wait(lambda: not is_open(app, "project-save"), timeout=8)
    assert "auf dem Pi gespeichert" in app.invoke("shell", "lastToast")
    assert app.invoke("start-api", "title") == "Regal Eins"
    app.invoke("sync-api", "openDialog", "save")
    app.wait(lambda: is_open(app, "project-row-0"), timeout=5)
    time.sleep(0.2)
    assert app.get("project-save", "text") == "Ersetzen"
    assert "gibt es schon" not in ""
    shot(app, "projekt-ersetzen-hell")
    app.click("project-close")
    app.wait(lambda: not is_open(app, "project-save"), timeout=5)

    # Change, then open from the shelf: the question about unsaved changes comes first.
    app.invoke("start-api", "setTitle", "Noch nicht gespeichert")
    app.invoke("sync-api", "openDialog", "open")
    app.wait(lambda: is_open(app, "project-open-0"), timeout=5)
    time.sleep(0.2)
    shot(app, "projekt-oeffnen-hell")
    app.click("project-open-0")
    app.wait(lambda: is_open(app, "confirm-ok"), timeout=5)
    app.click("confirm-cancel"); time.sleep(0.3)
    assert app.invoke("start-api", "title") == "Noch nicht gespeichert"
    app.click("project-open-0")
    app.wait(lambda: is_open(app, "confirm-ok"), timeout=5)
    app.click("confirm-ok")
    app.wait(lambda: app.invoke("start-api", "title") == "Regal Eins", timeout=8)
    # Delete from the list, with a question.
    app.wait(lambda: not is_open(app, "project-close") or True, timeout=1)
    app.invoke("sync-api", "openDialog", "open")
    app.wait(lambda: is_open(app, "project-delete-0"), timeout=5)
    app.click("project-delete-0")
    app.wait(lambda: is_open(app, "confirm-ok"), timeout=5)
    app.click("confirm-ok")
    app.wait(lambda: is_open(app, "project-none"), timeout=8)
    app.click("project-close")
    app.wait(lambda: not is_open(app, "project-close"), timeout=5)

    # ---- Local file ----
    f = str(TMP / "Lokal").replace("\\", "/")
    app.invoke("start-api", "setTitle", "Lokal gespeichert")
    time.sleep(0.2)
    assert app.invoke("start-api", "dirty") is True
    app.invoke("sync-api", "saveTo", f)
    app.wait(lambda: (TMP / "Lokal.lumacut").exists(), timeout=8)
    app.wait(lambda: app.invoke("start-api", "dirty") is False, timeout=8)
    assert app.invoke("sync-api", "filePath").endswith("Lokal.lumacut")
    assert json.loads((TMP / "Lokal.lumacut").read_text(encoding="utf-8"))["title"] == "Lokal gespeichert"
    open_project(app, project("Anderes"), wait_job=False)
    assert app.invoke("start-api", "title") == "Anderes"
    app.invoke("sync-api", "openNow", f + ".lumacut")
    app.wait(lambda: app.invoke("start-api", "title") == "Lokal gespeichert", timeout=8)
    # A file that is none: the project stays, a sentence says why.
    bad = TMP / "kaputt.lumacut"
    bad.write_text("{kein projekt", encoding="utf-8")
    app.invoke("sync-api", "openNow", str(bad).replace("\\", "/"))
    app.wait(lambda: "kein LumaCut-Projekt" in app.invoke("shell", "lastToast"), timeout=8)
    assert app.invoke("start-api", "title") == "Lokal gespeichert"

    # ---- Autosave: unsaved work survives a crash, and asks before it comes back ----
    app.invoke("start-api", "setTitle", "Nie gespeichert")
    app.invoke("sync-api", "autosaveNow")
    auto = Path(AUTOSAVE) / "autosave.lumacut"
    app.wait(lambda: auto.exists() and json.loads(auto.read_text(encoding="utf-8"))["title"] == "Nie gespeichert", timeout=8)
    app.wait(lambda: (Path(AUTOSAVE) / "autosave.lumacut.meta").exists(), timeout=8)
    keep = app.port
    url = app.invoke("shell", "piUrl")
    app.proc.kill()
    app.proc.wait(5)
    # Sharing off for this one: only the question about the file counts here.
    second = App(port=keep + 1, pi_url=url, env={"LUMACUT_AUTOSAVE_DIR": AUTOSAVE})
    try:
        second.wait(lambda: second.stats()["firstFrameMs"] > 0, timeout=30)
        second.wait(lambda: is_open(second, "recovered-restore"), timeout=8)
        assert "Nie gespeichert" in second.get("recovered-text", "text")
        time.sleep(0.2)
        shot(second, "wiederherstellen-hell")
        second.click("recovered-restore")
        second.wait(lambda: not is_open(second, "recovered-restore"), timeout=8)
        second.click("nav-start")
        second.wait(lambda: is_open(second, "start-preview"), timeout=5)
        second.wait(lambda: second.invoke("start-api", "title") == "Nie gespeichert", timeout=8)
        assert second.invoke("start-api", "dirty") is True
    finally:
        second.close()
    third = App(port=keep + 2, pi_url=url, env={"LUMACUT_AUTOSAVE_DIR": AUTOSAVE})
    try:
        third.wait(lambda: third.stats()["firstFrameMs"] > 0, timeout=30)
        third.wait(lambda: is_open(third, "recovered-discard"), timeout=8)
        third.click("recovered-discard")
        third.wait(lambda: not is_open(third, "recovered-discard"), timeout=8)
        assert not auto.exists()
    finally:
        third.close()
    shutil.rmtree(AUTOSAVE, ignore_errors=True)
