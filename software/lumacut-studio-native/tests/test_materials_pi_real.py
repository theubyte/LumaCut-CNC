"""Studio-Materialabgleich gegen den ECHTEN Pi-Dienst (pi400/marlin/web.py + materials.py).

Der Flask-Dienst läuft im selben Prozess auf einem freien Port (ohne Hardware,
Daten in einem Temp-Ordner über ``LUMACUT_DATA``); jeder Test bekommt eine
frische ``materials.json``. Ohne Flask oder ohne ``pi400`` im Checkout wird
übersprungen.
"""
from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from lumacut_materials.presets import Preset
from lumacut_materials.remote import HttpMaterialsTransport, MaterialsUnsupported
from lumacut_materials.sync import MaterialSync, PresetConflict

pytest.importorskip("flask")
from werkzeug.serving import make_server  # noqa: E402

PI400 = Path(__file__).resolve().parents[3] / "pi400"
if not (PI400 / "marlin" / "materials.py").is_file():  # pragma: no cover
    pytest.skip("pi400/marlin/materials.py nicht im Checkout", allow_module_level=True)


def _serve(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_port


@pytest.fixture(scope="module")
def pi_web(tmp_path_factory):
    data = tmp_path_factory.mktemp("pi-data")
    old_env = {k: os.environ.get(k) for k in ("LUMACUT_DATA", "LUMACUT_SKR")}
    os.environ["LUMACUT_DATA"] = str(data)
    os.environ["LUMACUT_SKR"] = str(data / "kein-usb")
    sys.path.insert(0, str(PI400))
    try:
        web = importlib.import_module("marlin.web")
        materials = importlib.import_module("marlin.materials")
    finally:
        sys.path.remove(str(PI400))
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert Path(web.DATA).is_relative_to(data)  # nie /var/lib/lumacut
    server, url = _serve(web.app)
    yield web, materials, url
    server.shutdown()
    server.server_close()


@pytest.fixture
def pi(pi_web, tmp_path):
    web, materials, url = pi_web
    web.MATERIALS = materials.MaterialStore(tmp_path / "pi" / "materials.json")
    return web, url


def device(tmp_path, name):
    return MaterialSync(tmp_path / name)


def named(sync, name):
    return next((p for p in sync.store.presets if p.name == name), None)


def t(url):
    return HttpMaterialsTransport(url, timeout=5)


def on_pi(web):
    return {m["name"]: m for m in web.MATERIALS.list()["materials"]}


def studio_preset(name="Buche 4 mm – Schnitt ✓", power=100.0, **kw) -> Preset:
    base = dict(name=name, material_id="birch_plywood", op="cut", laser_id="diode_10w",
                thickness_mm=4.0, power_pct=power, speed_mm_min=250.0, passes=3, z_step_mm=0.5,
                notes="Ölfrei, Kühlung „an“", warnings=["Rauch"], focus_start_mm=0.0)
    base.update(kw)
    return Preset(**base)


def test_first_contact_takes_pi_defaults(pi, tmp_path):
    web, url = pi
    a = device(tmp_path, "a")
    r = a.refresh(t(url))
    assert r.online and r.presets_changed and not r.rejected
    names = [p.name for p in a.store.presets]
    assert len(names) == 7 == len(set(names))
    assert "Pappelsperrholz" in names and "Pappelsperrholz – Gravur mittel" in names
    acryl = next(p for p in a.store.presets if p.name == "Acryl schwarz")
    assert (acryl.op, acryl.passes, acryl.z_step_mm, acryl.power_pct) == ("cut", 3, 0.5, 100.0)
    assert not a.pending
    # Nichts geändert → zweiter Abgleich ändert nichts und lädt nichts hoch.
    r2 = a.refresh(t(url))
    assert r2.online and not r2.presets_changed and not r2.uploaded
    assert web.MATERIALS.list()["revision"] == 1


def test_save_update_delete_roundtrip_between_devices(pi, tmp_path):
    web, url = pi
    a, b = device(tmp_path, "a"), device(tmp_path, "b")
    ta = t(url)
    a.refresh(ta)
    p = studio_preset()
    assert a.save_preset(p, ta) == "pi"
    stored = on_pi(web)[p.name]
    # Studio-Zusatzfelder überleben auf dem Pi, Kennung vom Pi übernommen.
    assert {k: stored[k] for k in ("material_id", "op", "laser_id", "notes", "warnings")} == {
        "material_id": "birch_plywood", "op": "cut", "laser_id": "diode_10w",
        "notes": "Ölfrei, Kühlung „an“", "warnings": ["Rauch"]}
    assert (stored["process"], stored["mode"], stored["passes"]) == ("Schneiden", "line", 3)
    assert named(a, p.name).id == stored["id"]
    b.refresh(t(url))
    seen = named(b, p.name)
    assert seen is not None and seen.to_dict() == named(a, p.name).to_dict()
    # Ändern = PUT auf dieselbe ID.
    rev = web.MATERIALS.list()["revision"]
    assert a.save_preset(studio_preset(power=85.0), ta) == "pi"
    assert on_pi(web)[p.name]["power_pct"] == 85.0
    assert on_pi(web)[p.name]["id"] == stored["id"]
    assert web.MATERIALS.list()["revision"] == rev + 1
    assert b.refresh(t(url)).presets_changed
    assert named(b, p.name).power_pct == 85.0
    # Android/Pi-Web ändern per PUT nur die Pi-Felder (ohne Studio-Zusatzfelder).
    rev = web.MATERIALS.list()["revision"]
    web.MATERIALS.update(stored["id"], {"name": p.name, "thickness_mm": 4.0, "process": "Gravieren",
                                        "mode": "fill", "power_pct": 30.0, "speed_mm_min": 2000.0,
                                        "passes": 1, "base_revision": rev})
    assert on_pi(web)[p.name]["laser_id"] == "diode_10w"  # Zusatzfelder bleiben
    b.refresh(t(url))
    android = named(b, p.name)
    assert (android.op, android.power_pct, android.laser_id) == ("engrave_medium", 30.0, "diode_10w")
    a.refresh(ta)
    # Löschen auf b → verschwindet auf dem Pi und bei a.
    assert b.delete_preset(p.name, t(url)) == "pi"
    assert p.name not in on_pi(web)
    a.refresh(t(url))
    assert named(a, p.name) is None


def test_values_outside_pi_ranges(pi, tmp_path):
    web, url = pi
    a = device(tmp_path, "a")
    ta = t(url)
    a.refresh(ta)
    eng = Preset(name="Leder Gravur", material_id="leather", op="engrave_medium",
                 laser_id="diode_10w", thickness_mm=None, power_pct=20, speed_mm_min=12000,
                 passes=1, line_interval_mm=None, depth_per_pass_mm=None)
    assert a.save_preset(eng, ta) == "pi"  # null/0-Werte weggelassen, Tempo begrenzt
    m = on_pi(web)["Leder Gravur"]
    assert (m["speed_mm_min"], m["interval_mm"], m["thickness_mm"]) == (6000.0, 0.1, 0.0)
    # Vom Pi abgelehnt (> 30 Durchgänge): bleibt lokal + ausstehend, Abgleich läuft weiter.
    bad = studio_preset("Zu dick", thickness_mm=40.0, depth_per_pass_mm=0.5, z_step_mm=0.0)
    assert a.save_preset(bad, ta) == "rejected"
    assert "30 Durchgänge" in a.last_message
    assert named(a, "Zu dick") is not None and a.pending
    good = studio_preset("Später offline")
    a.save_preset(good)  # offline
    r = a.refresh(t(url))
    assert r.online and any("Zu dick" in x for x in r.rejected)
    assert "Später offline" in on_pi(web) and "Zu dick" not in on_pi(web)
    assert "abgelehnt" in r.message


def test_conflicts_with_real_revisions(pi, tmp_path):
    web, url = pi
    a, b = device(tmp_path, "a"), device(tmp_path, "b")
    ta, tb = t(url), t(url)
    a.refresh(ta)
    a.save_preset(studio_preset("Kork"), ta)
    b.refresh(tb)
    # b ändert einen ANDEREN Eintrag → a hat nur eine veraltete Revision: still wiederholt.
    mdf = named(b, "MDF")
    mdf.power_pct = 90.0
    assert b.save_preset(mdf, tb) == "pi"
    assert a.save_preset(studio_preset("Kork", power=70.0), ta) == "pi"
    assert on_pi(web)["Kork"]["power_pct"] == 70.0
    # b ändert DENSELBEN Eintrag → a bekommt einen Konflikt mit der Pi-Fassung.
    b.refresh(tb)
    assert b.save_preset(studio_preset("Kork", power=55.0), tb) == "pi"
    with pytest.raises(PresetConflict) as ctx:
        a.save_preset(studio_preset("Kork", power=60.0), ta)
    assert ctx.value.remote["power_pct"] == 55.0
    assert a.resolve_conflict(ctx.value, "mine", ta) == "pi"
    assert on_pi(web)["Kork"]["power_pct"] == 60.0
    # Und umgekehrt „Fassung vom Pi“.
    b.refresh(tb)
    b.save_preset(studio_preset("Kork", power=40.0), tb)
    with pytest.raises(PresetConflict) as ctx:
        a.save_preset(studio_preset("Kork", power=99.0), ta)
    assert a.resolve_conflict(ctx.value, "pi", ta) == "pi"
    assert named(a, "Kork").power_pct == 40.0 == on_pi(web)["Kork"]["power_pct"]
    # Auf dem Pi gelöscht, lokal noch bearbeitet → Konflikt „gelöscht“.
    b.refresh(tb)
    b.delete_preset("Kork", tb)
    with pytest.raises(PresetConflict) as ctx:
        a.save_preset(studio_preset("Kork", power=33.0), ta)
    assert ctx.value.remote is None
    a.resolve_conflict(ctx.value, "mine", ta)
    assert on_pi(web)["Kork"]["power_pct"] == 33.0


def test_offline_queue_flush_and_offline_vs_remote_edit(pi, tmp_path):
    web, url = pi
    a, b = device(tmp_path, "a"), device(tmp_path, "b")
    a.refresh(t(url))
    a.save_preset(studio_preset("Pappel 3 mm"), t(url))
    # Pi weg: speichern, ändern und löschen landen in der Warteschlange.
    dead = HttpMaterialsTransport("http://127.0.0.1:%d" % _free_port(), timeout=0.5)
    r = a.refresh(dead)
    assert not r.online and "offline" in r.message
    assert a.save_preset(studio_preset("Neu offline"), dead) == "pending"
    assert a.delete_preset("Karton", None) == "pending"
    p = named(a, "Pappel 3 mm")
    p.power_pct = 77.0
    a.save_preset(p)
    # Inzwischen ändert b denselben Eintrag auf dem Pi.
    b.refresh(t(url))
    q = named(b, "Pappel 3 mm")
    q.power_pct = 11.0
    b.save_preset(q, t(url))
    r = a.refresh(t(url))
    assert r.online and r.conflicts
    names = on_pi(web)
    assert "Neu offline" in names and "Karton" not in names
    assert names["Pappel 3 mm"]["power_pct"] == 11.0          # Pi gewinnt
    assert names["Pappel 3 mm (lokal)"]["power_pct"] == 77.0  # eigene Fassung bleibt
    assert not a.pending


def test_old_pi_without_material_api(tmp_path):
    from flask import Flask
    server, url = _serve(Flask("alter-pi"))  # echte Flask-404 (HTML)
    try:
        a = device(tmp_path, "a")
        a.save_preset(studio_preset("Lokal"))
        r = a.refresh(t(url))
        assert not r.online and "lokale Datenbank" in r.message
        assert named(a, "Lokal") is not None and a.pending
        with pytest.raises(MaterialsUnsupported):
            t(url).get_presets()
    finally:
        server.shutdown()
        server.server_close()


def test_large_list_and_unicode(pi, tmp_path):
    web, url = pi
    for i in range(300):
        rev = web.MATERIALS.list()["revision"]
        web.MATERIALS.create({"name": "Prüfmaterial Nr. %03d – äöü ß €" % i, "thickness_mm": 3,
                              "process": "Gravieren", "mode": "fill", "power_pct": 20,
                              "speed_mm_min": 3000, "base_revision": rev})
    a = device(tmp_path, "a")
    start = time.monotonic()
    r = a.refresh(t(url))
    assert r.online and time.monotonic() - start < 10
    assert len(a.store.presets) == 307
    assert named(a, "Prüfmaterial Nr. 299 – äöü ß €") is not None
    saved = json.loads((tmp_path / "a" / "material_presets.json").read_text("utf-8"))
    assert "äöü ß €" in json.dumps(saved, ensure_ascii=False)
    r2 = a.refresh(t(url))
    assert not r2.presets_changed and not r2.uploaded


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
