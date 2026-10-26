"""Abgleich mit der Materialdatenbank auf dem Pi (Qt-frei).

Der Pi ist die gemeinsame Quelle für Windows-Studio, Android und Pi-Web
(Anforderung docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md §4). Dieses Modul
hält eine lokale Kopie, damit Studio auch ohne Pi arbeitet:

* **Datenbank**: ``refresh()`` holt ``GET /api/materials`` (``If-None-Match``
  mit dem zuletzt gesehenen ETag) und legt sie geprüft in
  ``materials_pi_cache.json`` ab. ``db()`` liefert in dieser Reihenfolge:
  Pi-Kopie (Cache), sonst die mitgelieferte ``materials.json``.
* **Eigene Presets**: ``material_presets.json`` (``PresetStore``) bleibt die
  lokale Ansicht (Ebenen-Panel und Dialog lesen sie). Mit dem Pi wird über
  ``id`` + ETag abgeglichen, Zustand in ``material_sync.json``:
  ``etags`` (id → zuletzt gesehener ETag), ``pending`` (offline geändert,
  noch hochzuladen), ``deleted`` (offline gelöscht, id → ETag).
* **Regeln beim Abgleich** (Pi gewinnt, nichts geht verloren):
  - Pi-Presets ersetzen lokale mit gleicher ID.
  - Offline geändert und auf dem Pi unverändert (gleicher ETag) → hochladen.
  - Offline geändert *und* auf dem Pi geändert → Pi-Fassung behalten, die
    lokale als „<Name> (lokal)“ mit neuer ID zusätzlich hochladen.
  - Lokal ohne ID (alte Presets vor dem Pi-Abgleich) → ID vergeben, hochladen.
  - Früher abgeglichen, nicht ausstehend, fehlt auf dem Pi → dort gelöscht,
    lokal entfernen.
* **Speichern/Löschen online**: ``save_preset``/``delete_preset`` schreiben
  sofort mit ``If-Match``; bei Konflikt (409/412) wird ``PresetConflict``
  geworfen, ``resolve_conflict`` übernimmt dann „meins“ oder „Pi“.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .db import DATA_PATH, OPERATION_LABELS, MaterialDB
from .presets import Preset, PresetStore, preset_id
from .remote import (MaterialsConflict, MaterialsError, MaterialsNoDatabase, MaterialsOffline,
                     MaterialsTransport, MaterialsUnsupported)

CACHE_NAME = "materials_pi_cache.json"
STATE_NAME = "material_sync.json"
PRESETS_NAME = "material_presets.json"
CACHE_FORMAT = "lumacut-materials-cache"
#: Felder, die nur der Pi verwaltet (nicht Teil von ``Preset``).
SERVER_FIELDS = ("etag", "revision", "updated_at", "updated_by")


class PresetConflict(Exception):
    """Preset wurde auf dem Pi geändert/gelöscht, seit es zuletzt gelesen wurde."""

    def __init__(self, local: Preset, remote: dict | None):
        what = "gelöscht" if remote is None else "geändert"
        super().__init__(f"„{local.name}“ wurde inzwischen auf dem Pi {what}.")
        self.local = local
        self.remote = remote


@dataclass
class SyncResult:
    source: str  # pi | cache | bundled
    online: bool = False
    db_changed: bool = False
    presets_changed: bool = False
    uploaded: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    #: vom Pi abgelehnt (HTTP 400, z. B. Wert außerhalb des Bereichs): „Name: Grund“;
    #: bleiben lokal und ausstehend.
    rejected: list[str] = field(default_factory=list)
    message: str = ""


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _reason(exc: Exception) -> str:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    return str(exc)


def preset_from_remote(item: dict) -> Preset:
    return Preset.from_dict({k: v for k, v in item.items() if k not in SERVER_FIELDS})


def fingerprint(item: dict | Preset) -> str:
    """Inhalt eines Presets ohne Server-Felder – erkennt Änderungen auf dem Pi
    unabhängig davon, ob der Server ETags je Preset oder eine Listen-Revision führt."""
    d = item.to_dict() if isinstance(item, Preset) else preset_from_remote(item).to_dict()
    d.pop("id", None)
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def preset_payload(p: Preset) -> dict:
    """JSON für ``PUT /api/materials/presets/<id>`` (Schema s. MATERIAL_DB_PI.md)."""
    return p.to_dict()


class MaterialSync:
    """Lokaler Cache + Abgleich. Thread-sicher (ein Lock um alle Zustände)."""

    def __init__(self, directory: str | Path, preset_path: str | Path | None = None) -> None:
        self.dir = Path(directory)
        self.cache_path = self.dir / CACHE_NAME
        self.state_path = self.dir / STATE_NAME
        self.store = PresetStore(Path(preset_path) if preset_path else self.dir / PRESETS_NAME)
        self._lock = threading.RLock()
        self.state = self._load_state()
        self.cache = self._load_cache()
        self.source = "cache" if self.cache else "bundled"
        self.online = False
        self.last_message = ""

    # -- Persistenz ----------------------------------------------------------
    def _load_state(self) -> dict:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return {"db_etag": str(raw.get("db_etag") or ""),
                "presets_etag": str(raw.get("presets_etag") or ""),
                "etags": dict(raw.get("etags") or {}),
                "base": dict(raw.get("base") or {}),
                "pending": list(raw.get("pending") or []),
                "deleted": dict(raw.get("deleted") or {})}

    def _load_cache(self) -> dict | None:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if raw.get("format") != CACHE_FORMAT:
                return None
            MaterialDB(raw["db"])  # nur gültige Kopien verwenden
            return raw
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def _save_state(self) -> None:
        atomic_write_json(self.state_path, self.state)

    def _save_presets(self) -> None:
        self.store.save()

    # -- Lesen ---------------------------------------------------------------
    def db_data(self) -> dict:
        with self._lock:
            if self.cache:
                return self.cache["db"]
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def db(self) -> MaterialDB:
        return MaterialDB(self.db_data())

    def describe(self) -> str:
        """Kurztext für die Oberfläche."""
        version = (self.cache or {}).get("version", "")
        if self.online and self.source != "pi":
            return "Materialliste vom Pi, Rechenwerte aus der mitgelieferten Datenbank"
        if self.source == "pi":
            return f"Materialdatenbank vom Pi{f' (Version {version})' if version else ''}"
        if self.source == "cache":
            return "Pi nicht verbunden – zuletzt geladene Pi-Datenbank"
        return "Mitgelieferte Materialdatenbank (Pi nicht verbunden)"

    @property
    def pending(self) -> list[str]:
        return list(self.state["pending"]) + list(self.state["deleted"])

    # -- Abgleich ------------------------------------------------------------
    def refresh(self, transport: MaterialsTransport) -> SyncResult:
        """Datenbank und Presets vom Pi holen, Ausstehendes hochladen.

        Wirft nie wegen Netzwerkproblemen: offline → ``online=False`` und
        Studio arbeitet mit Cache bzw. mitgelieferter Datenbank weiter."""
        with self._lock:
            result = SyncResult(source=self.source)
            try:
                try:
                    result.db_changed = self._refresh_db(transport)
                    self.source = "pi"
                except MaterialsNoDatabase:
                    pass  # nur Materialliste auf dem Pi: Presets abgleichen, Datenbank lokal
                result.presets_changed = self._refresh_presets(transport, result)
                self.online = True
            except MaterialsUnsupported as exc:
                self.online = False
                result.message = f"{exc} – Studio nutzt die lokale Datenbank"
            except MaterialsOffline as exc:
                self.online = False
                result.message = f"{exc} – offline, lokale Kopie aktiv"
            except MaterialsError as exc:
                self.online = False
                result.message = f"Material-Abgleich fehlgeschlagen: {exc}"
            result.source, result.online = self.source, self.online
            if result.online and not result.message:
                result.message = self.describe() + (
                    f", {len(result.uploaded)} Preset(s) hochgeladen" if result.uploaded else "")
            if result.rejected:
                result.message += "; vom Pi abgelehnt (bleibt lokal): " + "; ".join(result.rejected)
            self.last_message = result.message
            return result

    def _refresh_db(self, transport: MaterialsTransport) -> bool:
        etag = self.state["db_etag"] if self.cache else None
        remote = transport.get_materials(etag)
        if remote is None:  # 304: unverändert
            return False
        try:  # prüfen, bevor etwas ersetzt wird
            MaterialDB(remote.data)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise MaterialsError(f"Materialdatenbank vom Pi ungültig ({exc})") from None
        if self.cache and self.cache["db"] == remote.data:
            changed = False
        else:
            changed = True
        self.cache = {"format": CACHE_FORMAT, "etag": remote.etag, "version": remote.version,
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "db": remote.data}
        atomic_write_json(self.cache_path, self.cache)
        self.state["db_etag"] = remote.etag
        self._save_state()
        return changed

    def _refresh_presets(self, transport: MaterialsTransport, result: SyncResult) -> bool:
        before = [p.to_dict() for p in self.store.presets]
        st = self.state
        # 1. Offline-Löschungen nachholen.
        for pid, tag in list(st["deleted"].items()):
            try:
                transport.delete_preset(pid, tag or None)
            except MaterialsConflict:
                result.conflicts.append(pid)  # auf dem Pi geändert: Pi-Fassung bleibt
            except (MaterialsOffline, MaterialsUnsupported):
                raise
            except MaterialsError as exc:
                result.rejected.append(f"{pid}: {_reason(exc)}")
                continue  # bleibt in der Warteschlange
            st["deleted"].pop(pid, None)
            st["etags"].pop(pid, None)
            st["base"].pop(pid, None)
        # 2. Alte Presets ohne ID übernehmen.
        for p in self.store.presets:
            if not p.id:
                p.id = self._free_id(p.name)
                if p.id not in st["pending"]:
                    st["pending"].append(p.id)
        remote, list_etag = transport.get_presets()
        remote_by_id = {r["id"]: r for r in remote}
        local_by_id = {p.id: p for p in self.store.presets}
        merged: list[Preset] = []
        for rid, item in remote_by_id.items():
            tag = str(item.get("etag") or "")
            local = local_by_id.get(rid)
            if local is not None and rid in st["pending"]:
                if st["base"].get(rid) and fingerprint(item) != st["base"][rid]:
                    # beidseitig geändert: Pi behalten, lokale Fassung als Kopie
                    copy = Preset.from_dict({**local.to_dict(), "name": f"{local.name} (lokal)"})
                    copy.id = self._free_id(copy.name, taken=set(remote_by_id))
                    st["pending"].append(copy.id)
                    merged.append(copy)
                    result.conflicts.append(rid)
                    st["pending"].remove(rid)
                else:
                    merged.append(local)
                    continue
            merged.append(preset_from_remote(item))
            st["etags"][rid] = tag
            st["base"][rid] = fingerprint(item)
        for p in self.store.presets:
            if p.id in remote_by_id:
                continue
            if p.id in st["pending"]:
                merged.append(p)
            elif p.id in st["etags"] or p.id in st["base"]:
                st["etags"].pop(p.id, None)  # auf dem Pi gelöscht
                st["base"].pop(p.id, None)
            else:
                merged.append(p)
                st["pending"].append(p.id)
        # Namen eindeutig halten (PresetStore arbeitet mit Namen). Der Pi erlaubt
        # gleiche Namen (z. B. „Pappelsperrholz“ zum Schneiden und Gravieren).
        seen: set[str] = set()
        for p in merged:
            if p.name in seen:
                label = OPERATION_LABELS.get(p.op, p.op)
                name = f"{p.name} – {label}" if label else p.name
                p.name = name if name not in seen else f"{p.name} ({p.id[-6:]})"
            seen.add(p.name)
        self.store.presets = merged
        # 3. Ausstehende hochladen.
        for pid in list(st["pending"]):
            p = self.store.by_id(pid)
            if p is None:
                st["pending"].remove(pid)
                continue
            try:
                stored = transport.put_preset(pid, preset_payload(p), st["etags"].get(pid) or None)
            except MaterialsConflict as exc:
                result.conflicts.append(pid)
                if exc.current:
                    self._adopt_remote(pid, exc.current)
                st["pending"].remove(pid)
                continue
            except (MaterialsOffline, MaterialsUnsupported):
                raise
            except MaterialsError as exc:  # z. B. HTTP 400: lokal behalten, später erneut
                result.rejected.append(f"{p.name}: {_reason(exc)}")
                continue
            st["pending"].remove(pid)
            result.uploaded.append(self._record_stored(pid, stored))
        st["presets_etag"] = list_etag
        self._save_presets()
        self._save_state()
        return before != [p.to_dict() for p in self.store.presets]

    def _record_stored(self, pid: str, stored: dict) -> str:
        """Antwort eines erfolgreichen Schreibens übernehmen. Vergibt der Pi eine
        eigene ID (Variante B: POST), wird das lokale Preset umbenannt."""
        st = self.state
        new_id = str(stored.get("id") or pid)
        if new_id != pid:
            p = self.store.by_id(pid)
            if p is not None:
                p.id = new_id
            st["etags"].pop(pid, None)
            st["base"].pop(pid, None)
            self._save_presets()
        st["etags"][new_id] = str(stored.get("etag") or "")
        p = self.store.by_id(new_id)
        if stored.get("name"):  # so, wie der Pi es gespeichert hat
            st["base"][new_id] = fingerprint(dict(stored, id=new_id))
        elif p is not None:
            st["base"][new_id] = fingerprint(p)
        return new_id

    def _adopt_remote(self, pid: str, remote: dict) -> None:
        self.store.presets = [p for p in self.store.presets if p.id != pid]
        self.store.put(preset_from_remote(dict(remote, id=pid)))
        self.state["etags"][pid] = str(remote.get("etag") or "")
        self.state["base"][pid] = fingerprint(dict(remote, id=pid))

    def _free_id(self, name: str, taken: set[str] | None = None) -> str:
        used = {p.id for p in self.store.presets} | set(taken or ())
        pid, n = preset_id(name), 1
        while pid in used:
            n += 1
            pid = preset_id(f"{name}#{n}")
        return pid

    # -- Schreiben -----------------------------------------------------------
    def save_preset(self, preset: Preset, transport: MaterialsTransport | None = None) -> str:
        """Speichern: lokal sofort, auf dem Pi wenn verbunden.

        Rückgabe ``"pi"`` (auf dem Pi), ``"pending"`` (offline, wird beim
        nächsten Verbinden hochgeladen). Konflikt → ``PresetConflict``."""
        with self._lock:
            existing = next((p for p in self.store.presets if p.name == preset.name), None)
            if not preset.id:
                preset.id = existing.id if existing and existing.id else self._free_id(preset.name)
            self.store.put(preset)
            self._save_presets()
            st = self.state
            if transport is None:
                if preset.id not in st["pending"]:
                    st["pending"].append(preset.id)
                self._save_state()
                return "pending"
            try:
                stored = transport.put_preset(preset.id, preset_payload(preset),
                                              st["etags"].get(preset.id) or None)
            except MaterialsConflict as exc:
                raise PresetConflict(preset, exc.current) from None
            except (MaterialsOffline, MaterialsUnsupported):
                if preset.id not in st["pending"]:
                    st["pending"].append(preset.id)
                self._save_state()
                return "pending"
            except MaterialsError as exc:  # Pi lehnt ab (400): lokal behalten
                if preset.id not in st["pending"]:
                    st["pending"].append(preset.id)
                self._save_state()
                self.last_message = _reason(exc)
                return "rejected"
            if preset.id in st["pending"]:
                st["pending"].remove(preset.id)
            self._record_stored(preset.id, stored)
            self._save_state()
            return "pi"

    def resolve_conflict(self, conflict: PresetConflict, keep: str,
                         transport: MaterialsTransport) -> str:
        """``keep="mine"``: eigene Fassung über die Pi-Fassung schreiben;
        ``keep="pi"``: Pi-Fassung lokal übernehmen."""
        with self._lock:
            pid = conflict.local.id
            remote = conflict.remote
            if keep == "pi":
                if remote is None:
                    self.store.presets = [p for p in self.store.presets if p.id != pid]
                    self.state["etags"].pop(pid, None)
                    self.state["base"].pop(pid, None)
                else:
                    self._adopt_remote(pid, remote)
                if pid in self.state["pending"]:
                    self.state["pending"].remove(pid)
                self._save_presets()
                self._save_state()
                return "pi"
            if remote is None:
                self.state["etags"].pop(pid, None)
                self.state["base"].pop(pid, None)
            else:
                self.state["etags"][pid] = str(remote.get("etag") or "")
            return self.save_preset(conflict.local, transport)

    def delete_preset(self, name: str, transport: MaterialsTransport | None = None) -> str:
        with self._lock:
            p = next((q for q in self.store.presets if q.name == name), None)
            if p is None:
                return "local"
            self.store.remove(name)
            self._save_presets()
            st = self.state
            if p.id in st["pending"]:
                st["pending"].remove(p.id)
            if not p.id or (p.id not in st["etags"] and p.id not in st["base"]):
                self._save_state()
                return "local"  # nie auf dem Pi gewesen
            tag = st["etags"].get(p.id) or None
            if transport is not None:
                try:
                    transport.delete_preset(p.id, tag)
                    st["etags"].pop(p.id, None)
                    st["base"].pop(p.id, None)
                    self._save_state()
                    return "pi"
                except MaterialsConflict as exc:
                    raise PresetConflict(p, exc.current) from None
                except MaterialsError:
                    pass  # offline, alter Pi oder abgelehnt: später erneut
            st["deleted"][p.id] = tag or ""
            st["etags"].pop(p.id, None)
            st["base"].pop(p.id, None)
            self._save_state()
            return "pending"
