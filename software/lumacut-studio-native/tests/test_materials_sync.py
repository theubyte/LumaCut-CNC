"""Materialdatenbank auf dem Pi: Transport, Zwischenspeicher, Abgleich, Studio-Anbindung."""
from __future__ import annotations

import copy
import json

import pytest

from fake_materials_pi import FakeMaterialsPi
from lumacut_materials.db import DATA_PATH, MaterialDB
from lumacut_materials.presets import Preset, preset_id
from lumacut_materials.remote import (HttpMaterialsTransport, MaterialsNoDatabase,
                                      MaterialsOffline, MaterialsUnsupported,
                                      material_to_preset, preset_to_material)
from lumacut_materials.sync import MaterialSync, PresetConflict


def bundled() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def pi_db() -> dict:
    db = bundled()
    db["version"] = "pi-42"
    db["materials"][0]["name_de"] = "Pappel vom Pi"
    return db


def preset(name="Pappel 3 mm", power=80.0) -> Preset:
    return Preset(name=name, material_id="basswood_plywood", op="cut", laser_id="diode_10w",
                  thickness_mm=3.0, power_pct=power, speed_mm_min=300.0, passes=2, z_step_mm=0.5)


@pytest.fixture
def pi():
    fake = FakeMaterialsPi(pi_db())
    yield fake
    fake.close()


@pytest.fixture
def list_pi():
    fake = FakeMaterialsPi(variant="list")
    yield fake
    fake.close()


def http(fake) -> HttpMaterialsTransport:
    return HttpMaterialsTransport(fake.url, "k", timeout=3)


OFFLINE = "http://127.0.0.1:9"  # verweigert sofort


# --- Lesen / Offline ----------------------------------------------------------
def test_preset_id_is_stable_and_url_safe():
    a = preset_id("Pappel 3 mm – Schnitt")
    assert a == preset_id("Pappel 3 mm – Schnitt") and a.startswith("pappel-3-mm-schnitt-")
    assert preset_id("Äpfel") .startswith("aepfel-") and preset_id("Äpfel") != preset_id("Apfel")


def test_offline_uses_bundled_db(tmp_path):
    sync = MaterialSync(tmp_path)
    assert sync.source == "bundled" and sync.db().version == MaterialDB(bundled()).version
    r = sync.refresh(HttpMaterialsTransport(OFFLINE, timeout=1))
    assert not r.online and r.source == "bundled" and "offline" in r.message


def test_fetch_caches_pi_db_and_304(tmp_path, pi):
    sync = MaterialSync(tmp_path)
    r = sync.refresh(http(pi))
    assert r.online and r.source == "pi" and r.db_changed
    assert sync.db().material("basswood_plywood").name_de == "Pappel vom Pi"
    assert pi.requests[0][2].get("X-Lumacut-Key") == "k"
    # zweiter Abruf: If-None-Match → 304, nichts geändert
    r2 = sync.refresh(http(pi))
    assert not r2.db_changed and any(h.get("If-None-Match") for m, p, h in pi.requests[2:] if p == "/api/materials")
    # neuer Start ohne Pi: Kopie vom Pi bleibt
    again = MaterialSync(tmp_path)
    assert again.source == "cache" and again.db().version == "pi-42"
    assert not again.refresh(HttpMaterialsTransport(OFFLINE, timeout=1)).online
    assert again.db().version == "pi-42"


def test_invalid_pi_db_is_rejected(tmp_path, pi):
    pi.db = {"format": "kaputt"}
    sync = MaterialSync(tmp_path)
    r = sync.refresh(http(pi))
    assert not r.online and sync.source == "bundled"
    assert not (tmp_path / "materials_pi_cache.json").exists()


def test_old_pi_without_api(tmp_path):
    fake = FakeMaterialsPi(variant="none")
    try:
        sync = MaterialSync(tmp_path)
        sync.store.put(preset())
        sync.store.save()
        r = sync.refresh(http(fake))
        assert not r.online and "Material-API" in r.message and sync.source == "bundled"
        with pytest.raises(MaterialsUnsupported):
            http(fake).get_materials()
        assert sync.save_preset(preset("Neu"), http(fake)) == "pending"
    finally:
        fake.close()


# --- Presets: Variante A (Datenbank + Presets, ETag) ----------------------------
def test_save_online_and_merge_on_other_device(tmp_path, pi):
    win = MaterialSync(tmp_path / "win")
    p = preset()
    assert win.save_preset(p, http(pi)) == "pi"
    assert p.id in pi.presets and pi.presets[p.id]["power_pct"] == 80.0
    other = MaterialSync(tmp_path / "android")
    r = other.refresh(http(pi))
    assert r.presets_changed and other.store.get("Pappel 3 mm").power_pct == 80.0
    # gleiches Preset noch einmal (anderer Wert) behält die ID
    assert win.save_preset(preset(power=70.0), http(pi)) == "pi"
    assert len(pi.presets) == 1 and pi.presets[p.id]["power_pct"] == 70.0


def test_legacy_and_offline_presets_upload_on_connect(tmp_path, pi):
    sync = MaterialSync(tmp_path)
    sync.store.put(preset("Alt ohne ID"))
    sync.store.save()
    assert sync.save_preset(preset("Offline"), None) == "pending"
    assert set(sync.pending) == {sync.store.get("Offline").id}
    r = sync.refresh(http(pi))
    assert len(r.uploaded) == 2 and not sync.pending
    assert {p["name"] for p in pi.presets.values()} == {"Alt ohne ID", "Offline"}
    assert all(p.id for p in MaterialSync(tmp_path).store.presets)


def test_remote_delete_and_offline_delete(tmp_path, pi):
    sync = MaterialSync(tmp_path)
    a, b = preset("A"), preset("B")
    sync.save_preset(a, http(pi))
    sync.save_preset(b, http(pi))
    del pi.presets[a.id]  # anderes Gerät löscht A
    sync.refresh(http(pi))
    assert sync.store.names() == ["B"]
    assert sync.delete_preset("B", None) == "pending"  # offline gelöscht
    assert b.id in sync.pending
    sync.refresh(http(pi))
    assert pi.presets == {} and not sync.pending


def test_conflict_on_save_and_resolve(tmp_path, pi):
    sync = MaterialSync(tmp_path)
    p = preset()
    sync.save_preset(p, http(pi))
    pi.put_remote(p.id, dict(preset(power=55.0).to_dict(), id=p.id))
    with pytest.raises(PresetConflict) as info:
        sync.save_preset(preset(power=90.0), http(pi))
    assert info.value.remote["power_pct"] == 55.0
    assert sync.resolve_conflict(info.value, "pi", http(pi)) == "pi"
    assert sync.store.get("Pappel 3 mm").power_pct == 55.0
    with pytest.raises(PresetConflict) as info2:
        pi.put_remote(p.id, dict(preset(power=60.0).to_dict(), id=p.id))
        sync.save_preset(preset(power=95.0), http(pi))
    assert sync.resolve_conflict(info2.value, "mine", http(pi)) == "pi"
    assert pi.presets[p.id]["power_pct"] == 95.0


def test_offline_edit_vs_remote_edit_keeps_both(tmp_path, pi):
    sync = MaterialSync(tmp_path)
    p = preset()
    sync.save_preset(p, http(pi))
    sync.save_preset(preset(power=33.0), None)  # offline geändert
    pi.put_remote(p.id, dict(preset(power=66.0).to_dict(), id=p.id))  # Pi geändert
    r = sync.refresh(http(pi))
    assert p.id in r.conflicts
    names = {q.name: q.power_pct for q in sync.store.presets}
    assert names == {"Pappel 3 mm": 66.0, "Pappel 3 mm (lokal)": 33.0}
    assert {q["name"] for q in pi.presets.values()} == {"Pappel 3 mm", "Pappel 3 mm (lokal)"}


# --- Variante B (flache Liste mit Revision) -----------------------------------
def test_material_mapping_roundtrip():
    d = preset().to_dict()
    m = preset_to_material(dict(d, id="x1"))
    assert m["process"] == "Schneiden" and m["mode"] == "line" and m["thickness_mm"] == 3.0
    back = Preset.from_dict(material_to_preset(m))
    assert back.to_dict() == dict(d, id="x1")
    assert material_to_preset({"id": "b", "name": "Kork", "process": "Gravieren",
                               "interval_mm": 0.1, "builtin": True})["op"] == "engrave_medium"


def test_list_variant(tmp_path, list_pi):
    list_pi.put_remote("u-1", {"name": "Kork 2 mm", "thickness_mm": 2.0, "process": "Schneiden",
                               "mode": "line", "power_pct": 60, "speed_mm_min": 500, "passes": 1,
                               "interval_mm": 0, "depth_per_pass_mm": 0, "z_step_mm": 0,
                               "builtin": True})
    t = http(list_pi)
    with pytest.raises(MaterialsNoDatabase):
        t.get_materials()
    sync = MaterialSync(tmp_path)
    r = sync.refresh(http(list_pi))
    assert r.online and sync.source == "bundled" and sync.store.get("Kork 2 mm").op == "cut"
    tr = http(list_pi)
    tr.get_presets()
    p = preset()
    assert sync.save_preset(p, tr) == "pi"
    assert p.id in list_pi.items and list_pi.items[p.id]["process"] == "Schneiden"
    # unabhängige Änderung (Revision steigt) → stille Wiederholung, kein Konflikt
    list_pi.put_remote("u-1", dict(list_pi.items["u-1"], power_pct=65))
    assert sync.save_preset(preset(power=81.0), tr) == "pi"
    assert list_pi.items[p.id]["power_pct"] == 81.0
    # echte Änderung desselben Eintrags → Konflikt
    list_pi.put_remote(p.id, dict(list_pi.items[p.id], power_pct=10))
    with pytest.raises(PresetConflict):
        sync.save_preset(preset(power=82.0), tr)
    assert sync.delete_preset("Kork 2 mm", tr) in ("pi", "local")


# --- Studio-Anbindung (Qt) ------------------------------------------------------
class _Client:
    def __init__(self, url):
        self.base_url, self._api_key = url, ""


class _Machine:
    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class S(QObject):
            changed = Signal(str, str)
        self._s = S()
        self.connection_changed = self._s.changed
        self.connection_state = "disconnected"
        self.client = None


def test_studio_material_tools_follow_pi(qapp, tmp_path, pi):
    from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QMainWindow
    from lumacut_materials.dialog import MaterialTools

    win = QMainWindow()
    box = QGroupBox("Design")
    form = QFormLayout(box)
    combo = QComboBox()
    form.addRow("Material", combo)
    win.setCentralWidget(box)
    win.machine_panel = _Machine()
    tools = MaterialTools(win, sync=MaterialSync(tmp_path))
    assert not tools.pi_action.isEnabled() and tools.transport() is None
    assert not tools.refresh_from_pi(wait=True)
    first = combo.itemText(combo.findData("basswood_plywood"))
    assert "vom Pi" not in first

    m = win.machine_panel
    m.client, m.connection_state = _Client(pi.url), "connected"
    tools.refresh_from_pi(wait=True)
    assert tools.last_result.online
    assert "Pappel vom Pi" in combo.itemText(combo.findData("basswood_plywood"))
    assert tools.db.version == "pi-42"  # gleiches Objekt, an Ort und Stelle ersetzt

    dlg = tools.open()
    assert dlg.sync is tools.sync
    assert "Pappel vom Pi" in dlg.material.itemText(dlg.material.findData("basswood_plywood"))
    dlg.preset = preset("Aus dem Dialog")
    saved = dlg.save_preset("Aus dem Dialog")
    assert saved.id in pi.presets and "Pi" in dlg.sync_note

    m.client, m.connection_state = None, "disconnected"
    dlg.preset = preset("Offline-Dialog")
    dlg.save_preset("Offline-Dialog")
    assert "nächsten Verbinden" in dlg.sync_note
    m.client, m.connection_state = _Client(pi.url), "connected"
    m.connection_changed.emit("connected", "Verbunden")  # Hintergrund-Thread
    tools._thread.join(5)
    tools._collect()
    assert {p["name"] for p in pi.presets.values()} == {"Aus dem Dialog", "Offline-Dialog"}
    dlg.close()
    win.close()


def test_mapping_fits_pi_ranges():
    p = Preset(name="x" * 90, material_id="m", op="engrave_medium", laser_id="l",
               thickness_mm=None, power_pct=120.0, speed_mm_min=12000.0, passes=40,
               line_interval_mm=None, depth_per_pass_mm=None, z_step_mm=5.0)
    m = preset_to_material(p.to_dict())
    assert "interval_mm" not in m and None not in m.values()
    assert (len(m["name"]), m["power_pct"], m["speed_mm_min"], m["passes"], m["z_step_mm"],
            m["thickness_mm"]) == (80, 100.0, 6000.0, 30, 2.0, 0.0)
    assert m["material_id"] == "m" and m["op"] == "engrave_medium"


def test_list_variant_rejects_like_pi(tmp_path, list_pi):
    sync = MaterialSync(tmp_path)
    t = http(list_pi)
    sync.refresh(t)
    bad = preset("Zu dick")
    bad.thickness_mm, bad.depth_per_pass_mm, bad.z_step_mm = 40.0, 0.5, 0.0
    assert sync.save_preset(bad, t) == "rejected" and "30 Durchgänge" in sync.last_message
    assert sync.pending and not list_pi.items
    assert sync.save_preset(preset("Gut"), http(list_pi)) == "pi"  # frischer Transport
    assert [m["name"] for m in list_pi.items.values()] == ["Gut"]
