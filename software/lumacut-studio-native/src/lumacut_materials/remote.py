"""Transport zur Materialdatenbank auf dem Pi (Qt-frei, nur Standardbibliothek).

Zwei Server-Varianten werden erkannt (an der Antwort von ``GET /api/materials``):

Der echte Pi-Dienst (``pi400/marlin/materials.py``, ``docs/PI_API_REFERENZ.md``
§4.14) spricht **Variante B**; Variante A war die ursprünglich besprochene Form
und bleibt als Rückfall unterstützt.

**A – Datenbank + Presets** (nicht umgesetzt auf dem Pi)::

    GET    /api/materials                 Datenbank + version/etag (If-None-Match → 304)
    GET    /api/materials/presets         eigene Presets + etag der Liste
    PUT    /api/materials/presets/<id>    Preset anlegen/ersetzen (If-Match = etag)
    DELETE /api/materials/presets/<id>    Preset löschen (If-Match = etag)

Antworten werden tolerant gelesen (Hülle ``{"db": …}`` oder die Datenbank
direkt, ``ETag``-Header oder ``etag`` im JSON, Liste oder ``{"presets": […]}``),
damit kleine Abweichungen der Server-Version die Clients nicht brechen.

**B – flache Materialliste mit Revision** (``docs/ZUSAMMENARBEIT_CLAUDE_GROK.md``
Abschnitt 3)::

    GET    /api/materials                  {"revision": n, "materials": [Material, …]}
    POST   /api/materials                  Material ohne id + base_revision
    PUT    /api/materials/<id>             Material + base_revision
    DELETE /api/materials/<id>?base_revision=n
    409    {"error": …, "revision": n}

Dort gibt es keine vollständige Datenbank (``get_materials`` wirft
``MaterialsNoDatabase``, Studio rechnet mit der mitgelieferten weiter); die
Einträge der Liste werden als Presets abgebildet (``material_to_preset`` /
``preset_to_material``). Die Listen-Revision ersetzt den ETag; eine veraltete
Revision bei einem *unveränderten* Eintrag wird still mit der neuen wiederholt,
nur echte Änderungen desselben Eintrags melden einen Konflikt.

``MaterialsTransport`` ist die Schnittstelle; ``HttpMaterialsTransport`` die
Umsetzung über HTTP. Tests und andere Transporte (z. B. ein späteres
``machine.materials_client``) implementieren dieselben vier Methoden.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

MATERIALS_PATH = "/api/materials"
PRESETS_PATH = "/api/materials/presets"
AUTH_HEADER = "X-LumaCut-Key"
DEFAULT_TIMEOUT_S = 5.0
#: Erlaubte Preset-IDs (auch Teil der URL).
PRESET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class MaterialsError(Exception):
    """Pi hat die Anfrage abgelehnt (HTTP 4xx/5xx)."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class MaterialsOffline(MaterialsError):
    """Pi nicht erreichbar (Netz, Zeitüberschreitung) – lokal weiterarbeiten."""


class MaterialsUnsupported(MaterialsError):
    """Pi kennt die Material-API nicht (älterer Pi-Dienst, HTTP 404/405)."""


class MaterialsNoDatabase(MaterialsUnsupported):
    """Pi führt nur eine Materialliste (Variante B), keine vollständige Datenbank."""


class MaterialsConflict(MaterialsError):
    """ETag passt nicht (HTTP 409/412): jemand hat inzwischen geändert.

    ``current`` ist das Preset, wie es jetzt auf dem Pi liegt (``None`` = gelöscht
    oder vom Server nicht mitgeliefert)."""

    def __init__(self, message: str, current: dict | None = None, status: int | None = 409):
        super().__init__(message, status, current)
        self.current = current


@dataclass
class RemoteDB:
    data: dict
    etag: str
    version: str


class MaterialsTransport(Protocol):
    def get_materials(self, etag: str | None = None) -> RemoteDB | None: ...
    def get_presets(self) -> tuple[list[dict], str]: ...
    def put_preset(self, preset_id: str, data: dict, if_match: str | None = None) -> dict: ...
    def delete_preset(self, preset_id: str, if_match: str | None = None) -> None: ...


def check_preset_id(preset_id: str) -> str:
    if not isinstance(preset_id, str) or not PRESET_ID_RE.match(preset_id):
        raise ValueError("Ungültige Preset-ID: %r" % (preset_id,))
    return preset_id


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return None


def _reason(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or "")
    return ""


def _etag(headers, body: Any) -> str:
    tag = (headers.get("ETag") or "") if headers is not None else ""
    if not tag and isinstance(body, dict):
        tag = str(body.get("etag") or "")
    return tag.strip()


def is_material_list(body: Any) -> bool:
    """Variante B: ``{"revision": n, "materials": [...]}`` ohne Datenbank-Kopf."""
    return (isinstance(body, dict) and isinstance(body.get("materials"), list)
            and "db" not in body and body.get("format") != "lumacut-materials")


def unwrap_db(body: Any) -> dict:
    """Datenbank aus der Antwort: ``{"db": {...}}`` oder direkt ``{"format": ...}``."""
    if isinstance(body, dict):
        if isinstance(body.get("db"), dict):
            return body["db"]
        if body.get("format") == "lumacut-materials":
            return body
    raise MaterialsError("Pi-Antwort enthält keine Materialdatenbank")


# --- Variante B: Material ↔ Preset -------------------------------------------
PROCESS_BY_OP = {"cut": ("Schneiden", "line"), "engrave_surface": ("Markieren", "fill")}
#: Zusatzfelder, die Studio im Material mitschickt (der Pi darf sie ignorieren).
STUDIO_FIELDS = ("material_id", "op", "laser_id", "focus_start_mm", "air_assist",
                 "notes", "warnings", "source")


#: Wertebereiche des Pi (pi400/marlin/materials.py ``validate``); Studio-Werte
#: außerhalb würden mit HTTP 400 abgelehnt. Gleiche Grenzen wie
#: ``Preset.layer_values`` (das, was die Maschine tatsächlich fährt).
PI_LIMITS = {"power_pct": (0.0, 100.0), "speed_mm_min": (1.0, 6000.0),
             "thickness_mm": (0.0, 50.0), "interval_mm": (0.01, 5.0),
             "depth_per_pass_mm": (0.0, 50.0), "z_step_mm": (0.0, 2.0)}
PI_MAX_PASSES = 30
PI_MAX_NAME = 80


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _clamp(key: str, value: Any) -> float:
    low, high = PI_LIMITS[key]
    return min(high, max(low, _num(value, low)))


def preset_to_material(data: dict) -> dict:
    """Studio-Preset → Material des Pi (Variante B).

    Fehlende/leere Werte werden weggelassen (der Pi setzt Standardwerte; ``null``
    lehnt er ab), Zahlen auf die Bereiche des Pi begrenzt."""
    process, mode = PROCESS_BY_OP.get(str(data.get("op", "")), ("Gravieren", "fill"))
    try:
        passes = int(round(_num(data.get("passes"), 1.0)))
    except (OverflowError, ValueError):
        passes = 1
    out = {"name": str(data.get("name") or "").strip()[:PI_MAX_NAME],
           "thickness_mm": _clamp("thickness_mm", data.get("thickness_mm") or 0.0),
           "process": process, "mode": mode,
           "power_pct": _clamp("power_pct", data.get("power_pct")),
           "speed_mm_min": _clamp("speed_mm_min", data.get("speed_mm_min")),
           "passes": min(PI_MAX_PASSES, max(1, passes)),
           "depth_per_pass_mm": _clamp("depth_per_pass_mm", data.get("depth_per_pass_mm") or 0.0),
           "z_step_mm": _clamp("z_step_mm", data.get("z_step_mm") or 0.0)}
    if data.get("line_interval_mm"):
        out["interval_mm"] = _clamp("interval_mm", data["line_interval_mm"])
    out.update({k: data[k] for k in STUDIO_FIELDS if k in data and data[k] is not None})
    if data.get("id"):
        out["id"] = data["id"]
    return out


def material_to_preset(m: dict) -> dict:
    process = str(m.get("process", ""))
    op = m.get("op")
    # ``op`` ist ein Studio-Zusatzfeld; ändert Android/Pi-Web nur ``process`` (PUT
    # behält Zusatzfelder), gilt ``process``.
    if not op or PROCESS_BY_OP.get(str(op), ("Gravieren", "fill"))[0] != process:
        op = {"Schneiden": "cut", "Markieren": "engrave_surface"}.get(process, "engrave_medium")
    out = {"id": str(m.get("id", "")), "name": m.get("name") or str(m.get("id", "")),
           "material_id": m.get("material_id", ""), "op": op, "laser_id": m.get("laser_id", ""),
           "thickness_mm": (m.get("thickness_mm") or None),
           "power_pct": m.get("power_pct", 0.0), "speed_mm_min": m.get("speed_mm_min", 0.0),
           "passes": m.get("passes", 1), "z_step_mm": m.get("z_step_mm", 0.0),
           "depth_per_pass_mm": m.get("depth_per_pass_mm", 0.0),
           "line_interval_mm": (m.get("interval_mm") or None) if op != "cut" else None,
           "source": m.get("source") or ("pi" if m.get("builtin") else "planner")}
    for k in ("focus_start_mm", "air_assist", "notes", "warnings"):
        if k in m:
            out[k] = m[k]
    if m.get("builtin"):
        out["builtin"] = True
    return out


def _same_material(a: dict | None, b: dict | None) -> bool:
    skip = {"updated", "etag", "revision"}
    if a is None or b is None:
        return a is b
    return {k: v for k, v in a.items() if k not in skip} == \
        {k: v for k, v in b.items() if k not in skip}


def unwrap_presets(body: Any) -> list[dict]:
    items = body.get("presets") if isinstance(body, dict) else body
    if not isinstance(items, list):
        raise MaterialsError("Pi-Antwort enthält keine Presetliste")
    out = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("preset"), dict):
            item = dict(item["preset"], **{k: v for k, v in item.items() if k != "preset"})
        if isinstance(item, dict) and item.get("id"):
            out.append(item)
    return out


def unwrap_preset(body: Any, headers=None) -> dict:
    item = body.get("preset") if isinstance(body, dict) and isinstance(body.get("preset"), dict) \
        else body
    item = dict(item) if isinstance(item, dict) else {}
    tag = _etag(headers, body) or str(item.get("etag") or "")
    if tag:
        item["etag"] = tag
    return item


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


class HttpMaterialsTransport:
    """HTTP-Transport (gleiche Konventionen wie ``machine.client``: kein Proxy,
    keine Umleitungen, ``X-LumaCut-Key`` falls gesetzt)."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = DEFAULT_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self._api_key = (api_key or "").strip()
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        #: ``None`` (noch unbekannt), ``"db"`` (Variante A) oder ``"list"`` (Variante B)
        self.mode: str | None = None
        self._revision: int | None = None
        self._listing: dict[str, dict] = {}

    def __repr__(self) -> str:  # Schlüssel nie in Logs
        return "HttpMaterialsTransport(%r)" % self.base_url

    @classmethod
    def from_client(cls, client, timeout: float = DEFAULT_TIMEOUT_S) -> "HttpMaterialsTransport":
        """Aus einem verbundenen ``machine.client.LumaCutClient``."""
        return cls(client.base_url, getattr(client, "_api_key", ""), timeout)

    def _request(self, method: str, path: str, body: Any = None,
                 headers: dict | None = None) -> tuple[int, Any, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self._api_key:
            req.add_header(AUTH_HEADER, self._api_key)
        for k, v in (headers or {}).items():
            if v:
                req.add_header(k, v)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                status, raw, hdrs = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as exc:
            status, hdrs = exc.code, exc.headers
            raw = exc.read() if exc.fp is not None else b""
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            raise MaterialsOffline("Pi nicht erreichbar (%s): %s"
                                   % (self.base_url, getattr(exc, "reason", exc))) from None
        payload = _decode(raw)
        if status == 304:
            return status, None, hdrs
        if status == 404 and method == "DELETE":
            return status, payload, hdrs  # schon gelöscht: Ziel erreicht
        if status in (404, 405, 501):
            raise MaterialsUnsupported("Pi ohne Material-API (HTTP %d)" % status, status, payload)
        if status in (409, 412):
            current = payload.get("current") if isinstance(payload, dict) else None
            raise MaterialsConflict(_reason(payload) or "Preset wurde inzwischen auf dem Pi geändert",
                                    current if isinstance(current, dict) else None, status)
        if status in (401, 403):
            raise MaterialsError("Pi lehnt ab (HTTP %d): %s" % (status, _reason(payload)
                                                                 or "X-LumaCut-Key prüfen"),
                                 status, payload)
        if status >= 300:
            raise MaterialsError("Pi lehnt ab (HTTP %d): %s" % (status, _reason(payload)
                                                                 or "ohne Begründung"),
                                 status, payload)
        return status, payload, hdrs

    def get_materials(self, etag: str | None = None) -> RemoteDB | None:
        status, body, hdrs = self._request("GET", MATERIALS_PATH, headers={
            "If-None-Match": etag if self.mode != "list" else None})
        if status == 304:
            self.mode = "db"
            return None
        if is_material_list(body):
            self._take_listing(body)
            raise MaterialsNoDatabase("Pi führt eine Materialliste ohne Datenbank", status, None)
        self.mode = "db"
        db = unwrap_db(body)
        version = body.get("version") if isinstance(body, dict) and "db" in body else None
        return RemoteDB(db, _etag(hdrs, body), str(version if version is not None
                                                   else db.get("version", "")))

    # -- Variante B ----------------------------------------------------------
    def _take_listing(self, body: dict) -> list[dict]:
        self.mode = "list"
        try:
            self._revision = int(body.get("revision"))
        except (TypeError, ValueError):
            self._revision = None
        self._listing = {str(m["id"]): m for m in body["materials"]
                         if isinstance(m, dict) and m.get("id")}
        return list(self._listing.values())

    def _list(self) -> list[dict]:
        _status, body, _h = self._request("GET", MATERIALS_PATH)
        if not is_material_list(body):
            raise MaterialsError("Pi-Antwort enthält keine Materialliste")
        return self._take_listing(body)

    def _rev_tag(self) -> str:
        return "" if self._revision is None else "rev-%d" % self._revision

    def _list_write(self, method: str, preset_id: str, body: dict | None) -> dict | None:
        """Schreiben mit ``base_revision``; bei 409 neu laden und – falls der Eintrag
        unverändert ist – einmal mit der neuen Revision wiederholen."""
        known = self._listing.get(preset_id)
        for attempt in (0, 1):
            rev = self._revision
            if method == "POST":
                payload = {k: v for k, v in (body or {}).items() if k != "id"}
                path, payload = MATERIALS_PATH, dict(payload, base_revision=rev)
            elif method == "PUT":
                path = MATERIALS_PATH + "/" + urllib.parse.quote(preset_id)
                payload = dict(body or {}, id=preset_id, base_revision=rev)
            else:
                path = MATERIALS_PATH + "/" + urllib.parse.quote(preset_id) + (
                    "" if rev is None else "?base_revision=%d" % rev)
                payload = None
            try:
                _s, resp, _h = self._request(method, path, body=payload)
            except MaterialsUnsupported as exc:
                if method == "PUT" and exc.status == 404:  # inzwischen gelöscht
                    self._listing.pop(preset_id, None)
                    raise MaterialsConflict("Eintrag wurde inzwischen auf dem Pi gelöscht",
                                            None, 404) from None
                raise
            except MaterialsConflict:
                if attempt:
                    raise
                self._list()
                now = self._listing.get(preset_id)
                if method != "POST" and not _same_material(known, now):
                    raise MaterialsConflict(
                        "Eintrag wurde inzwischen auf dem Pi " + ("gelöscht" if now is None
                                                                  else "geändert"),
                        None if now is None else dict(material_to_preset(now),
                                                      etag=self._rev_tag())) from None
                continue
            if isinstance(resp, dict) and resp.get("revision") is not None:
                try:
                    self._revision = int(resp["revision"])
                except (TypeError, ValueError):
                    pass
            item = resp.get("material") if isinstance(resp, dict) else None
            if isinstance(item, dict) and item.get("id"):
                self._listing[str(item["id"])] = item
            elif method == "DELETE":
                self._listing.pop(preset_id, None)
            return item
        return None

    # -- gemeinsame Schnittstelle --------------------------------------------
    def _ensure_mode(self) -> None:
        """Variante erkennen, bevor geschrieben wird (frischer Transport, z. B.
        Speichern im Dialog vor dem ersten Abgleich)."""
        if self.mode is None:
            try:
                self.get_materials()
            except MaterialsNoDatabase:
                pass

    def get_presets(self) -> tuple[list[dict], str]:
        self._ensure_mode()
        if self.mode == "list":
            items = self._list()
            tag = self._rev_tag()
            return [dict(material_to_preset(m), etag=tag) for m in items], tag
        _status, body, hdrs = self._request("GET", PRESETS_PATH)
        return unwrap_presets(body), _etag(hdrs, body)

    def put_preset(self, preset_id: str, data: dict, if_match: str | None = None) -> dict:
        self._ensure_mode()
        if self.mode == "list":
            check_preset_id(preset_id)
            method = "PUT" if preset_id in self._listing else "POST"
            item = self._list_write(method, preset_id, preset_to_material(dict(data, id=preset_id)))
            stored = material_to_preset(item) if item else dict(data, id=preset_id)
            return dict(stored, etag=self._rev_tag())
        path = PRESETS_PATH + "/" + urllib.parse.quote(check_preset_id(preset_id))
        _status, body, hdrs = self._request("PUT", path, body=dict(data, id=preset_id),
                                            headers={"If-Match": if_match})
        stored = unwrap_preset(body, hdrs)
        return stored or dict(data, id=preset_id)

    def delete_preset(self, preset_id: str, if_match: str | None = None) -> None:
        self._ensure_mode()
        if self.mode == "list":
            check_preset_id(preset_id)
            if preset_id in self._listing:
                self._list_write("DELETE", preset_id, None)
            return
        path = PRESETS_PATH + "/" + urllib.parse.quote(check_preset_id(preset_id))
        self._request("DELETE", path, headers={"If-Match": if_match})
