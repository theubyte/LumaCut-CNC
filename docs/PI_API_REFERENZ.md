# Pi 400: HTTP-API-Referenz (für Web-UI und Clients)

Diese Referenz beschreibt **jeden** HTTP-Endpunkt und **jedes** `op` von
`POST /api/action` des Pi-Dienstes (`pi400/marlin/web.py`, Flask). Alle
Angaben sind aus dem Code abgeleitet (`web.py`, `transport.py`,
`placement.py`, `smart_cam.py`, `camera_calibration.py`,
`firmware_flash.py`) und, wo ohne Hardware möglich, mit dem Flask-Testclient
nachgeprüft. Punkte, die nur an der echten Maschine prüfbar sind, tragen
**⚠ Hardware**.

`tests/test_pi_api_reference_doc.py` liest Routen, `op`-Namen und
Statusfelder aus dem Code und schlägt fehl, wenn hier einer fehlt. Wer einen
Endpunkt, ein `op` oder ein Statusfeld ergänzt, ergänzt es auch hier.

Verwandte Dokumente: [PI_BETRIEB.md](PI_BETRIEB.md) (Betrieb, Updates),
[PI_STATUS_UND_OFFENE_PUNKTE.md](PI_STATUS_UND_OFFENE_PUNKTE.md) (Stand,
offene Punkte), [MACHINE_API.md](../software/lumacut-studio-native/docs/MACHINE_API.md)
(wie Studio diese API nutzt).

---

## 1. Grundlagen

| Punkt | Wert |
| --- | --- |
| Basis-URL | `http://lumacut.local:8080` (Port aus `LUMACUT_HTTP`, Standard 8080). TCP 23 (`LUMACUT_TCP`) ist der LightBurn-Kanal, **kein** HTTP. |
| Server | Flask `threaded=True`: jede Anfrage in eigenem Thread. Lange Fahrten blockieren nur ihre eigene Anfrage. |
| Anfragen mit Formular | `POST /api/action`, `/api/settings`, `/api/commission`: `application/x-www-form-urlencoded` (oder `multipart/form-data`). Felder werden **nur** aus dem Formular gelesen (`request.form`), nicht aus Query-String oder JSON. |
| Datei-Uploads | `POST /api/upload`, `/api/firmware`: `multipart/form-data`, Feld `file`. |
| JSON-Body | nur `PUT /api/camera/calibration` (`application/json`). |
| Antwortformat | JSON. Ausnahmen: `GET /` (HTML), `/api/jobs/<name>/content` (`text/plain`), `/api/camera/snapshot` (`image/jpeg`). |
| Header jeder Antwort | `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. |
| Max. Anfragegröße | 32 MB (`MAX_CONTENT_LENGTH`). Größer → **413 als HTML** (siehe unten). |
| Zahlen | Dezimalpunkt (`12.5`), nicht Komma. `float("abc")` scheitert mit 400 und englischem Python-Text (`could not convert string to float: 'abc'`). |

### 1.1 Erfolg und Fehler

- Erfolg: HTTP 200. Aktionen liefern immer `message` (deutscher Klartext, für
  den Nutzer gedacht), manche zusätzlich Daten (`queue`, `origin`,
  `placement`, `frame`, `position`, `detail`).
- Fehler aus dem Code: JSON `{"error": "<deutscher Text>"}`. Abbildung im
  Fehlerhandler (`handle_error`):

| Ausnahme auf dem Pi | HTTP | Typische Bedeutung |
| --- | --- | --- |
| `ValueError` (auch `FirmwareImageError`), `RuntimeError` (auch `MarlinCommandError`), `PermissionError` | **400** | Eingabe ungültig, Vorbedingung fehlt, Steuerung belegt, Marlin meldet Fehler |
| `TimeoutError`, `ConnectionError` | **503** | SKR nicht per USB identifiziert, Marlin-Antwort überfällig, Kamera fehlt, E-Stop ohne USB |
| alles andere (z. B. `serial.SerialException` bei `op=connect` ohne USB-Gerät) | **500** | `{"error": "Interner Fehler – Pi-Protokoll ansehen"}` |
| eigene Codes | 403 / 409 / 413 / 415 | nur `PUT /api/camera/calibration` (Abschnitt 4.13) |

- **Nicht-JSON-Fehler** (Werkzeug-Standardseiten, `text/html`): 404 für
  unbekannte Pfade, 405 für falsche Methode (z. B. `GET /api/action`), 413
  bei mehr als 32 MB. Ein Client darf deshalb nicht blind `response.json()`
  aufrufen: erst Text lesen, dann JSON versuchen (siehe JS-Helfer in
  Abschnitt 9.2; die alte `index.html` macht es ebenso).
- Status 400 heißt „abgelehnt, nichts passiert“ **nur bei Vorbedingungen**.
  Scheitert eine bereits laufende Fahrt (z. B. Marlin `Error:` mitten in
  `op=home`), kommt ebenfalls 400, aber die Maschine kann sich schon bewegt
  haben. Danach immer `/api/status` neu lesen.

### 1.2 Gemeinsame Vorbedingung „Steuerung frei“ (`local_owner()`)

Viele Operationen rufen zuerst `local_owner()` auf. Reihenfolge der Prüfungen
und Fehlertexte:

| Prüfung | Fehler |
| --- | --- |
| `owner == "frame"` | 400 `Rahmenfahrt läuft – abwarten oder abbrechen` |
| `owner` gesetzt (`web`, `job`, `lightburn`, `firmware`, `monitor`, `shutdown`) | 400 `Steuerung belegt durch <owner> – LightBurn zuerst trennen` (der Text nennt LightBurn auch bei `job`/`firmware`) |
| kein USB / keine LumaCut-Kennung | 503 `Marlin SKR noch nicht per USB identifiziert` |
| `state != "Idle"` (z. B. `Busy`) | 400 `SKR beschäftigt: Busy` |

`local_owner()` prüft den **E-Stop-Riegel nicht** selbst. Das erledigt der
nächste Marlin-Befehl: `RuntimeError` `M112-Notstopp aktiv; keine weiteren
Bewegungen` bzw. bei Fahrroutinen `SKR nicht bereit / Notstopp aktiv` oder
`Marlin USB nicht bereit oder Notstopp verriegelt` (503). `op=frame` prüft den
Riegel ausdrücklich.

Kurzzeichen in den Tabellen unten:

- **frei**: `local_owner()` muss bestehen.
- **referenziert**: `homed == true` (nach `op=home` bzw. G28 über LightBurn).
- **freigegeben**: Mechanik-Freigabe `config.validated == true`
  (`/api/commission`), intern `homing_verified`. Ohne sie lehnen Homing,
  Upload, Start, Rahmen und jede Fahrbewegung über den G-Code-Wächter ab
  (`Mechanik noch nicht freigegeben`,
  `Mechanik/Z-Endschalter nicht verifiziert`,
  `Fahrbewegung erst nach bestätigter Mechanik-Konfiguration freigeben`).

### 1.3 Besitzer (`owner`) und Sperren

| `owner` in `/api/status` | Wer hält die Steuerung | Ende |
| --- | --- | --- |
| `"Frei"` | niemand | – |
| `"web"` | kurz während einer synchronen Web-Aktion (`home`, `jog`, `probe`, `park`, `moveto`, …) | mit der HTTP-Antwort |
| `"job"` | Einzelauftrag (`start`/`autorun`) oder Warteschlange (`queue_run`) | Worker-Ende (fertig, Fehler, Abbruch) |
| `"frame"` | Rahmenfahrt (`op=frame`) | Worker-Ende |
| `"lightburn"` | LightBurn per TCP 23 verbunden | LightBurn trennt |
| `"firmware"` | Firmware-Update läuft | Update fertig oder Fehler |
| `"monitor"` / `"shutdown"` | Heartbeat (M114 alle 2 s, nur wenn frei) / Dienst-Ende | Sekundenbruchteile |

Zusätzlich gibt es `job_lock`: Auftrag, Warteschlange und Rahmen schließen
sich gegenseitig aus (`Ein Auftrag läuft bereits`, `Ein Auftrag oder Rahmen
läuft bereits`). Das Stopp-Signal `stop_job` ist für alle drei dasselbe
(`op=abort`, `op=estop`).

---

## 2. Endpunkt-Übersicht

| Methode | Pfad | Content-Type der Anfrage | Zweck |
| --- | --- | --- | --- |
| GET | `/` | – | alte Web-UI (`pi400/marlin/index.html`) |
| GET | `/api/status` | – | kompletter Maschinen-, Auftrags-, Rahmen-, Warteschlangenstatus |
| POST | `/api/action` | form | alle Maschinenaktionen über `op` (Abschnitt 4) |
| POST | `/api/settings` | form | Z-/Fokus-/Tasterwerte dauerhaft speichern |
| POST | `/api/commission` | form | Mechanik-Freigabe ein/aus |
| POST | `/api/firmware` | multipart | SKR-Firmware über USB flashen |
| POST | `/api/upload` | multipart | G-Code-Auftrag prüfen und speichern |
| GET | `/api/jobs` | – | gespeicherte Aufträge auflisten |
| GET | `/api/jobs/<name>/content` | – | G-Code eines Auftrags als Text |
| POST | `/api/jobs/<name>/delete` | – | Auftrag löschen |
| GET | `/api/jobs/<name>/geometry` | – | Motivgrenzen und Abtastkandidaten |
| GET | `/api/camera/snapshot` | – | ein JPEG der Kopfkamera |
| GET | `/api/app/android` | – | neueste Android-App auf dem Pi (Version, Prüfsumme) – Abschnitt 4.15 |
| GET | `/api/app/android.apk` | – | die APK zum Installieren |
| GET | `/api/camera/calibration` | – | Kamera-Kalibrierung lesen |
| PUT | `/api/camera/calibration` | JSON | Kamera-Kalibrierung schreiben (mit Revision) |
| GET | `/api/materials` | – | Material-Datenbank lesen (Abschnitt 4.14) |
| POST | `/api/materials` | JSON | Material anlegen (mit `base_revision`) |
| PUT | `/api/materials/<name>` | JSON | Material ändern (`<name>` = Material-`id`) |
| DELETE | `/api/materials/<name>` | Query | Material löschen (`?base_revision=n`) |

`<name>` ist ein reiner Dateiname (`Path(name).name == name`, kein `/`, kein
`..`), in URLs mit `encodeURIComponent` kodieren.

Alle `op`-Werte von `POST /api/action`:

| Gruppe | `op` |
| --- | --- |
| Not-Aus | `estop`, `estop_reset` |
| Verbindung/Abfrage | `connect`, `info`, `position`, `endstops` |
| Bewegung | `home`, `jog`, `park`, `moveto`, `probe` |
| Zubehör | `light`, `exhaust` |
| Ursprung/Platzierung | `origin_set`, `origin_clear`, `place`, `place_clear` |
| Aufträge | `start`, `autorun`, `abort`, `frame` |
| Warteschlange | `queue_add`, `queue_run`, `queue_pause`, `queue_skip`, `queue_remove`, `queue_clear` |

Unbekanntes oder fehlendes `op` → 400 `Unbekannte Marlin-Aktion: <op>`.

---

## 3. `GET /api/status`

Liefert immer HTTP 200 (auch ohne USB), außer der Dienst ist abgestürzt.

### 3.1 Sperrverhalten: `busy` und `stale_ms`

`machine_snapshot()` wartet **höchstens 0,25 s** (`STATUS_LOCK_WAIT_S`) auf
die Maschinensperre. Homing, Parken, Abtasten, `moveto`, `jog` und jede
Rahmenkante (M400) halten die Sperre für die ganze Fahrt.

- Sperre frei: vollständiger, konsistenter Status, `busy: false`,
  `stale_ms: 0`. Wird als Cache gemerkt.
- Sperre belegt: **letzter vollständiger Status aus dem Cache**, darüber
  live gelesen: `state`, `owner`, `homed`, `z_homed`, `emergency_latched`,
  `laser_armed`, `laser_cooling_fan_on`, `position`, `fault`,
  `workpiece_surface_z`, `connected`. Dazu `busy: true` und `stale_ms` = Alter
  des Cache-Anteils in ms.
- Sonderfall: Sperre belegt **und noch nie ein Cache** (direkt nach
  Dienststart): `stale_ms: null`, und **alle Transportfelder außer den
  Live-Feldern fehlen** (z. B. `identity`, `recent`, `stream_window`). Clients
  müssen fehlende Felder vertragen.
- Die Felder aus `web.py` (`job`, `frame`, `queue`, `activity`, `origin`,
  `config`, `camera`, …) sind immer aktuell, auch bei `busy: true`.
- `position` ist während einer Fahrt die **letzte von M114 gemeldete**
  Position, nicht die Live-Position (Marlin meldet erst nach der Fahrt).
  ⚠ Hardware

### 3.2 Felder

Transportfelder (`MarlinTransport.status()` in `transport.py`):

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `connected` | bool | USB offen **und** LumaCut-Kennung per M115 bestätigt |
| `state` | string | `"Disconnected"`, `"Idle"`, `"Busy"` (Befehl unterwegs) |
| `owner` | string | `"Frei"` oder Besitzer (Abschnitt 1.3) |
| `identity` | string | M115-Kennung der SKR-Firmware (enthält den Build-Stempel), `""` ohne Verbindung |
| `homed` | bool | XYZ referenziert; fällt nach E-Stop, USB-Verlust, Firmware-Update auf `false` |
| `z_homed` | bool | Z referenziert |
| `z_probe_supported` | bool \| null | Firmware meldet `Cap:Z_PROBE` (null = noch unbekannt) |
| `emergency_latched` | bool | M112-Riegel aktiv: alles außer `estop`/`estop_reset` wird abgelehnt |
| `firmware_upload_supported` | bool | Firmware meldet `Cap:BINARY_FILE_TRANSFER:1` (Voraussetzung für `/api/firmware`) |
| `firmware_update` | object | `{state, progress, message}`; `state` ∈ `idle`, `uploading`, `rebooting`, `done`, `error`; `progress` 0..100 |
| `homing_verified` | bool | = Mechanik-Freigabe (`config.validated`) |
| `position` | [x, y, z] \| null | letzte M114-Position in Maschinen-mm |
| `fault` | string | letzter Fehler (z. B. nach E-Stop), `""` wenn keiner |
| `lights` | bool | Licht (LED-Streifen an PC8) an |
| `light_brightness` | number | eingestellte Helligkeit 1..100 % (gilt, wenn `lights` an) |
| `light_dimmable` | bool \| null | `true` = Firmware dimmt (`M355`), `false` = alte Firmware (nur `M7`/`M9`), `null` = noch nicht geprüft |
| `light_effects` | bool | Lichteffekte bei Referenzieren, Auftragsstart, Auftragsende, Fehler |
| `exhaust` | bool | Abluft (M8) an |
| `laser_armed` | bool | Laser per `M3 I` scharf; außerhalb eines Auftrags immer `false` |
| `laser_cooling_fan_on` | bool | Laserversorgung/Kühlung (FAN1/PC6) an |
| `workpiece_surface_z` | number \| null | gemessene Werkstückoberfläche (Z, mm) nach `op=probe`/G30 |
| `safe_zone_xy_mm` | number | 30.0: Bänder X<30 und Y<30 sind Homing-/Parkzone, dort wird nie geschnitten |
| `probe_xy_offset_mm` | [dx, dy] \| null | Versatz Taster ↔ Laserpunkt |
| `cutting_bounds` | object | `{x_min: 30, y_min: 30, x_max: 390, y_max: 370}` |
| `probe_minimum_z` | number \| null | tiefstes erlaubtes Z über dem Werkstück |
| `laser_focus_z` | number \| null | Fokus-Z = Oberfläche + Fokusabstand − Schalter-zu-Spitze-Offset |
| `cooldown_remaining_s` | int \| null | Nachlauf der Laserkühlung in s |
| `serial_errors` | int | Zähler serieller Fehler |
| `command_count` | int | Zähler gesendeter Befehle |
| `stream_window` | int | Streaming-Fenster 1..8 (`LUMACUT_STREAM_WINDOW`, Standard 4) |
| `streamed_count` | int | Zähler gestreamter Auftragszeilen |
| `lightburn_clients` | int | Zähler bisheriger LightBurn-Verbindungen (kein „gerade verbunden“; dafür `owner == "lightburn"`) |
| `recent` | string[] | letzte 25 Zeilen des seriellen Protokolls |

Felder aus `web.py` (`status()`):

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `busy` | bool | Status aus Cache (Abschnitt 3.1) |
| `stale_ms` | int \| null | Alter des Cache-Anteils |
| `activity` | string | `"framing"` (Rahmen läuft), `"job"` (Auftrag `homing`/`probing`/`running` oder Warteschlange `running`/`pausing`), sonst `"idle"`. Achtung: Firmware-Update, LightBurn und kurze Web-Fahrten erscheinen hier als `"idle"`; dafür `owner` lesen. |
| `job` | object | `{file, state, line, total, error, probe, phase}`; `phase` = genauerer Schritt solange aktiv: `homing`, `probing`, `focusing` (Höhenkorrektur rechnen), `running`, `finishing` (letzte gepufferte Bahnen), `parking`; sonst `null`. Ein `autorun` beginnt direkt mit `homing`/`probing`, nie mit `running`/`line=0`. `error` ist ein deutscher Satz mit dem nächsten Schritt (Abbruch: `Abgebrochen`); `probe` = `{done, total}` der Abtastpunkte bei `autorun` (ab `probing`, bleibt danach stehen), sonst `null`; `state` ∈ `idle`, `homing`, `probing`, `running`, `complete`, `aborted`, `error`. Bleibt nach dem Ende auf `complete`/`aborted`/`error` stehen. |
| `frame` | object | `{state, mode, line, total, error}`; `state` ∈ `idle`, `running`, `complete`, `aborted`, `error`; `mode` ∈ `""`, `box`, `hull` |
| `queue` | object | `{items, state, current, max}` (siehe unten) |
| `origin` | object | `{modes, anchors, coord_convention, user, placement}` (siehe unten) |
| `features` | string[] | Merkmale des Pi-Stands: `autorun_mesh` = `op=autorun` tastet selbst ab und korrigiert den Fokus (Apps laden den Auftrag ohne Z hoch), `materials` = `/api/materials` vorhanden, `app_update` = `/api/app/android` (App-Updates über den Pi). Fehlt bei älteren Pi-Ständen. |
| `coord_convention` | string | `"origin_top_right"`: Bedeutung der Ankernamen (siehe `op=place`). Fehlt bei Pi-Ständen vor 2026-10-26; Studio tauscht dann links/rechts. |
| `estimated_tip_gap_mm` | number \| null | geschätzter Abstand Spitze ↔ Werkstück (nur wenn referenziert, Position und Oberfläche bekannt). Schätzung, keine Messung. |
| `estimated_focus_adjust_mm` | number \| null | Fokusabstand − `estimated_tip_gap_mm` (nur Anzeige) |
| `firmware` | string | immer `"marlin"` |
| `expected_pwm` | string | `"PA1 / M3 I / S0..255"` (Info) |
| `io` | object | Klartext-Belegung `laser_supply_switch`, `laser_pwm`, `fan_cooldown`, `exhaust`, `lights`, `aux` (Info) |
| `config` | object | gespeicherte Einstellungen: `validated`, `z_clearance_mm`, `focus_gap_mm`, `z_switch_tip_offset_mm`, `probe_offset_x_mm`, `probe_offset_y_mm`, `travels` `{x: 390, y: 370, z: 90}`, `user_origin`, `light_brightness`, `light_effects` |
| `camera` | object | `{device, available}`: Gerätepfad (`LUMACUT_CAMERA`, Standard `/dev/video0`) und ob er existiert (sagt nichts darüber, ob ffmpeg ein Bild bekommt) |

`job.line` / `job.total`: `total` = Zahl der Auftragszeilen; `line` zählt
Zeilen, die **an Marlin übergeben** wurden. Durch das Streaming-Fenster
(`stream_window`) und den Marlin-Planerpuffer läuft `line` der tatsächlichen
Bewegung voraus. Für eine Fortschrittsanzeige reicht das; für „jetzt fertig“
gilt nur `job.state == "complete"`. ⚠ Hardware

`queue`:

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `items` | array | Einträge in Reihenfolge (ohne internen `sha`) |
| `items[].id` | int | fortlaufend ab 1, für `queue_skip`/`queue_remove` |
| `items[].file` | string | Auftragsdatei |
| `items[].origin` | string | eingefrorener Ursprung (`absolute`, `current`, `user`) |
| `items[].anchor` | string | eingefrorener Bezugspunkt |
| `items[].dx` | number | eingefrorener Versatz X in mm |
| `items[].dy` | number | eingefrorener Versatz Y in mm |
| `items[].target` | [x, y] \| null | Zielpunkt des Bezugspunkts |
| `items[].bounds` | object \| null | Motivgrenzen nach Versatz `{xmin, ymin, xmax, ymax}` |
| `items[].state` | string | `queued`, `running`, `done`, `skipped`, `aborted`, `error` |
| `items[].error` | string | Fehlertext |
| `state` | string | `idle`, `running`, `pausing` (hält nach dem laufenden Auftrag), `paused`, `stopped` (Fehler/Abbruch), `complete` |
| `current` | int \| null | `id` des laufenden Eintrags |
| `max` | int | 50 |

`origin`:

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `modes` | string[] | `["absolute", "current", "user"]` |
| `anchors` | string[] | `["tl", "tr", "bl", "br", "center"]`, Ecken **wie von vorne gesehen**: X0/Y0 (Endschalter) liegt oben rechts, Maschinen-X wächst nach links, Y nach vorne. `tr` = (kleinstes X, kleinstes Y) = Schalterecke, `tl` = (größtes X, kleinstes Y), `br` = (kleinstes X, größtes Y), `bl` = (größtes X, größtes Y). Seit 2026-10-26, erkennbar an `coord_convention` = `origin_top_right`; davor bedeutete `l` kleines X. |
| `coord_convention` | string | wie oben im Status |
| `user` | [x, y] \| null | gespeicherter Benutzer-Ursprung |
| `placement` | object \| null | aktive Platzierung `{file, origin, anchor, dx, dy, target, bounds, travel}` |

---

## 4. Endpunkte im Detail

### 4.1 `GET /`

Liefert `index.html` aus `pi400/marlin/`. Die neue Web-UI ersetzt diese
Datei; weitere statische Dateien liefert der Dienst **nicht** aus
(`static_folder=None`). CSS/JS also inline einbetten oder eine Route
ergänzen lassen.

### 4.2 `POST /api/action` – Not-Aus

#### `op=estop`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | **keine**: nimmt weder `local_owner()` noch die Maschinensperre; wirkt auch bei Besitzer `job`, `frame`, `lightburn`, `firmware` |
| Wirkung | setzt `stop_job` (Auftrag/Rahmen/Warteschlange brechen ab), schreibt `M112` direkt auf USB (Marlin EMERGENCY_PARSER), setzt `emergency_latched`, `homed`/`z_homed`/`laser_armed` = false, `fault` |
| Erfolg | 200 `{"message": "Marlin M112 ausgelöst – physischen Not-Aus prüfen"}` |
| Fehler | 503 `Software-Notstopp NICHT übertragen: USB getrennt, physischen Not-Aus benutzen` (**Riegel wird trotzdem gesetzt**); 503/500 `Software-Notstopp fehlgeschlagen: …` bei Schreibfehler |
| Danach | SKR hängt in `kill()`; erst SKR-Reset (Taste oder 24 V/USB trennen), dann `op=estop_reset`, dann neu referenzieren. ⚠ Hardware |

Idempotent: mehrfaches Senden ist unschädlich. UI soll bei Netzfehler
wiederholen (Abschnitt 9.2).

#### `op=estop_reset`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | Besitzer frei (`Steuerung belegt: <owner>`); SKR muss neu gestartet sein |
| Wirkung | schließt USB, versucht Neuverbindung (M115 + Kennung); bei Erfolg Riegel und `fault` gelöscht |
| Erfolg | 200 `Notstopp quittiert: SKR neu gestartet, bitte neu referenzieren`, oder `Kein Notstopp aktiv` wenn kein Riegel |
| Fehler | 400 `SKR antwortet noch nicht: Reset-Taste am SKR drücken oder 24 V und USB kurz trennen (…)` – Riegel bleibt |
| Dauer | einige Sekunden (Port öffnen, M115) |

### 4.3 `POST /api/action` – Verbindung und Abfragen

#### `op=connect`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | kein Riegel, kein Client verbunden (sonst 400 `M112-Notstopp verriegelt – SKR zurücksetzen, dann Notstopp quittieren` bzw. `SKR noch nicht bereit, während Client verbunden ist`) |
| Wirkung | öffnet USB (falls zu), prüft M115 + LumaCut-Kennung. Der Heartbeat versucht das ohnehin alle 8 s. |
| Erfolg | 200 `Marlin M115 + LumaCut-Kennung bestätigt` |
| Fehler | 400 `SKR meldet kein echtes Marlin M115`, `Fremde/alte Marlin-Firmware: LumaCut CNC Kennung fehlt`; 503 bei Timeout; **500** `Interner Fehler – Pi-Protokoll ansehen`, wenn das USB-Gerät fehlt (`SerialException` wird nicht abgebildet) |

#### `op=info` / `op=position` / `op=endstops`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | **frei** |
| Wirkung | sendet `M115` / `M114` / `M119` (Timeout 12 s) |
| Erfolg | 200 `{"message": "<Marlin-Antwortzeilen, mit \n getrennt>"}` |
| Fehler | Abschnitt 1.2; 503 `Keine Marlin-Bestätigung vor Fristablauf` |

### 4.4 `POST /api/action` – Bewegung

Alle Bewegungen sind **synchron**: die HTTP-Antwort kommt erst nach dem Ende
der Fahrt. Client-Timeout großzügig wählen (Abschnitt 8.3).

#### `op=home`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | **frei**, **freigegeben** (sonst 400 `Mechanik/Z-Endschalter nicht verifiziert`), kein Riegel |
| Wirkung | atomare sichere Referenzfahrt (dieselbe wie LightBurn-G28): erst X/Y in die leere 30-mm-Zone, dann Z auf Maschinenboden Z=0, dann Z-Rückzug `z_clearance_mm`. Verwirft eine Platzierung mit `origin=current`. |
| Erfolg | 200 `X/Y zuerst, danach Maschinenboden Z=0 und Z-Rückzug: referenziert.` |
| Fehler | Abschnitt 1.2; Marlin-Fehler 400; 503 bei Timeout (Teilschritte bis 150 s) |
| Hinweis | Die 30-mm-Bänder an X0 und Y0 müssen frei von Material sein. ⚠ Hardware |

#### `op=jog`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `axis` | string | `X`, `Y`, `Z` (Groß-/Kleinschreibung egal) |
| `distance` | number | genau `-10`, `-1`, `-0.1`, `0.1`, `1`, `10` (mm) |

| | |
| --- | --- |
| Vorbedingungen | **referenziert** (zuerst geprüft: 400 `Marlin muss zuerst referenziert werden`), dann **frei**, Fahrt nur mit **Freigabe** (Wächter) |
| Wirkung | `M5 I`, `G91`, `G0 <Achse><±d> F1800` (Z: F360), `M400`, `G90`, `M114`. Verwirft Platzierung `current`. Prüft **keine** Arbeitsraumgrenzen selbst; Marlin-Softendstops begrenzen. ⚠ Hardware |
| Erfolg | 200 `Bewegung ausgeführt: X 1.0` |
| Fehler | 400 `Ungültige Achse oder Schrittweite` |

#### `op=park`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | **frei**, **referenziert** (`Parken erst nach gültiger XYZ-Referenzfahrt`), kein Riegel (`SKR nicht bereit / Notstopp aktiv`) |
| Wirkung | wie LightBurn-M2/Auftragsende: Laser aus (`M5 I`), Z nur nach oben (max. aus aktueller Höhe, Rückzug, Oberfläche + Abstand; >90 mm → Fehler), dann `G0 X0 Y0 F9000`; startet Kühlungsnachlauf |
| Erfolg | 200 `Geparkt: Laser aus, Z-Rückzug, X0/Y0` |
| Fehler | 400 `Z-Position außerhalb konfiguriertem Z-Hub`, `Parkhöhe unbekannt: keine Fahrt` |

#### `op=moveto`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `x` | number | 0..390 (Maschinen-mm) |
| `y` | number | 0..370 |

| | |
| --- | --- |
| Vorbedingungen | **frei**, **referenziert** (`Fahren erst nach gültiger XYZ-Referenzfahrt`), kein Riegel, Laser nicht scharf (`Fahren bei aktivem Laser unzulässig`) |
| Wirkung | Laser-aus-Fahrt (für Kamera-Scan/Positionieren): `M5 I`, `M400`, Z nur anheben auf `z_clearance_mm`, `G0 X Y F9000`, `M400`, `M114`. Darf in die 30-mm-Zone (Laser aus). Verwirft Platzierung `current`. |
| Erfolg | 200 `{"message": "Kopf auf X120.0 Y80.0", "position": [x, y, z]}` |
| Fehler | 400 `Ziel außerhalb X0..390 / Y0..370` (auch bei fehlendem/NaN-Wert); nicht-numerisch → 400 Python-Text |

#### `op=probe`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `x`, `y` | number, optional | beide oder keiner; 30..390 / 30..370 |

| | |
| --- | --- |
| Vorbedingungen | **frei**, **referenziert** (`Vor dem Abtasten referenzieren`), Freigabe, Firmware mit `Cap:Z_PROBE` (sonst 400 `SKR meldet Cap:Z_PROBE:0 …`), Tasterversatz gesetzt (`X/Y-Tasterversatz muss zuerst kalibriert sein`), Laser aus |
| Wirkung | optional `G0 X Y` (Timeout 60 s), dann G30-Abtastung unter der aktuellen Laser-XY (mit Tasterversatz). Setzt `workpiece_surface_z`; Maschinen-Z0 bleibt unverändert. |
| Erfolg | 200 `{"message": "Werkstückoberfläche Z=… mm, Fokus Z=… mm", "detail": "<bis 6 Marlin-Zeilen>"}` |
| Fehler | 400 `Abtastpunkt außerhalb X30..390 / Y30..370`, `G30 ohne Tasterkontakt bis Z…: kein Material unter dem Taster …`, `Z-Taster war schon beim G30-Start … gedrückt …`, `G30-Kontakt Z… unter Maschinenboden …` ⚠ Hardware |

### 4.5 `POST /api/action` – Zubehör

#### `op=light`

Dimmbarer 24-V-LED-Streifen an PC8 (Firmware: Marlin-Gehäuselicht `M355 S<0|1> P<0-255>`,
Hardware-PWM ~1,1 kHz).

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `on` | string, optional | `1` = ein, sonst aus; ohne `on` bleibt der Zustand |
| `brightness` | number, optional | 1..100 %; wird gespeichert (`config.light_brightness`) |
| `effects` | string, optional | `1`/`0`: Lichteffekte an/aus (gespeichert, `config.light_effects`) |

| | |
| --- | --- |
| Vorbedingungen | **frei** (also nicht während Auftrag/Rahmen/LightBurn), SKR verbunden |
| Wirkung | `M355 S1 P<brightness·2,55>` bzw. `M355 S0`. Alte Firmware ohne `M355` („Unknown command“): `M7` an, `M9` aus (danach `M8`, falls Abluft an war); `light_dimmable` wird dann `false`. |
| Erfolg | 200 `{"message": "Licht EIN · 60 %", "lights": true, "brightness": 60, "dimmable": true}` |
| Fehler | 400 `Helligkeit 1..100 %` |
| Lichteffekte | Der Pi spielt sie selbst (nicht abschaltbar pro Ereignis, nur gesamt über `effects`): Referenzieren = 2× aufblitzen, Auftragsstart = hochdimmen, Auftragsende = 3× „atmen“, Auftragsfehler = 3× schnell blinken (nicht bei Abbruch durch den Bediener). Danach gilt wieder `lights`/`light_brightness`. Nur mit Dimm-Firmware. |
| UI | Schalter aus `lights`, Regler aus `light_brightness` (nur zeigen, wenn `light_dimmable` nicht `false`) |

#### `op=exhaust`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `on` | string | `1` = ein, alles andere = aus |

| | |
| --- | --- |
| Vorbedingungen | **frei** |
| Wirkung | Abluft `M8` an, `M9` aus. Das Licht bleibt unberührt (alte Firmware: `M9` schaltete auch PC8, der Pi schaltet es dann wieder ein). |
| Erfolg | 200 `Abluft EIN` / `Abluft AUS` |

### 4.6 `POST /api/action` – Ursprung und Platzierung

Platzierung verschiebt einen gespeicherten Auftrag so, dass sein Bezugspunkt
(`anchor`) auf einem Ursprung (`origin`) liegt. **Nichts bewegt sich.**

- `origin`: `absolute` (Koordinaten wie im G-Code), `current` (aktuelle
  Kopf-XY per frischem M114), `user` (gespeicherter Benutzer-Ursprung).
- `anchor`: `tl`, `tr`, `bl`, `br`, `center` der **geschnittenen** Bahnen
  (Standard `tr` = Schalterecke). Ecken **wie von vorne gesehen**: X0/Y0 (Endschalter) liegt oben rechts, Maschinen-X wächst nach links, Y nach vorne. `tr` = (kleinstes X, kleinstes Y) = Schalterecke, `tl` = (größtes X, kleinstes Y), `br` = (kleinstes X, größtes Y), `bl` = (größtes X, größtes Y). Seit 2026-10-26, erkennbar an `coord_convention` = `origin_top_right`; davor bedeutete `l` kleines X.
- Prüfung auf die tatsächlich gesendeten Zeilen: alle Fahrten in X0..390 /
  Y0..370, alle Laserbahnen in X30..390 / Y30..370, G-Code-Wächter.
- Eine gespeicherte Platzierung verfällt bei: neuem Upload der Datei, Löschen,
  `place_clear`, anderer Platzierung; `current` zusätzlich bei `home`, `jog`,
  `moveto`; `user` bei `origin_set`/`origin_clear`; inhaltlich geänderter
  Datei (SHA-256).

#### `op=origin_set`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `x`, `y` | number, optional | beide oder keiner; 30..390 / 30..370. Ohne: aktuelle Kopf-XY |

| | |
| --- | --- |
| Vorbedingungen | **frei**, **referenziert** (`Vor dem Setzen des Ursprungs referenzieren`) |
| Wirkung | speichert `config.user_origin` (dauerhaft, `config.json`); verwirft Platzierung `user` |
| Erfolg | 200 `{"message": "Benutzer-Ursprung gesetzt: X… Y…", "origin": {…}}` |
| Fehler | 400 `Ursprung X… Y… außerhalb des Schneidbereichs X30..390 / Y30..370`, `Kopfposition unbekannt – Position abfragen` |

#### `op=origin_clear`

Keine Parameter, **keine** Vorbedingung. Löscht `user_origin` (dauerhaft) und
eine Platzierung `user`. 200 `{"message": "Benutzer-Ursprung gelöscht", "origin": {…}}`.

#### `op=place`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `name` | string | gespeicherte Auftragsdatei |
| `origin` | string | `absolute` (Standard), `current`, `user` |
| `anchor` | string | `tr` (Standard), `tl`, `bl`, `br`, `center` (sichtbare Ecke, siehe oben) |

| | |
| --- | --- |
| Vorbedingungen | **frei**, Freigabe (Wächter-Prüfung); bei `current`/`user` **referenziert** |
| Wirkung | berechnet und speichert die Platzierung (`origin.placement`); `absolute` löscht sie |
| Erfolg | 200 `{"message": "Platziert: … – Motiv X…", "placement": {file, origin, anchor, dx, dy, target, bounds, travel}}` |
| Fehler | 400 `Unbekannte Auftragsdatei`, `Ursprung muss absolute, current oder user sein`, `Bezugspunkt muss tl, tr, bl, br oder center sein`, `Kein Benutzer-Ursprung gesetzt (op=origin_set)`, `Auftrag ohne Laserbahnen: Bezugspunkt nicht bestimmbar`, `Auftrag enthält relative X/Y-Bewegungen (G91) – nur absolut platzierbar`, `Platziertes Motiv … liegt außerhalb des Schneidbereichs …`, `Platzierter Auftrag fährt außerhalb des Arbeitsbereichs …` |

#### `op=place_clear`

Keine Parameter, keine Vorbedingung. 200 `{"message": "Platzierung aufgehoben: Aufträge laufen absolut", "origin": {…}}`.

### 4.7 `POST /api/action` – Aufträge

#### `op=start`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `name` | string | gespeicherte Auftragsdatei |
| `placement` | string, optional | `1` = gespeicherte Platzierung (`op=place`) verwenden |
| `origin` | string, optional | `current`/`user`: sofort platzieren (wie `op=place`, wird gespeichert); leer/`absolute` = absolut |
| `anchor` | string, optional | mit `origin` |

| | |
| --- | --- |
| Vorbedingungen | **frei**, **referenziert** (`Vor dem Job referenzieren`), **freigegeben** (`Mechanik noch nicht freigegeben`), kein anderer Auftrag/Rahmen (`Ein Auftrag läuft bereits`), LightBurn darf nicht dazwischenkommen (`LightBurn hat inzwischen die Steuerung`) |
| Wirkung | asynchron: Worker-Thread unter Besitzer `job`. `M5 I`, dann Zeilen streamen (G0/G1 im Fenster `stream_window`, alles andere einzeln); `G28` → sichere Referenzfahrt, `G30` → Abtastung, `M2` ignoriert; am Ende `drain`, Parken. Status über `job`. |
| Erfolg | 200 `Job gestartet: <name>` (sofort) |
| Fehler (Start) | 400 `Unbekannte Auftragsdatei`, `Keine gültige Platzierung für … – neu platzieren (op=place)`, `Auftrag seit dem Platzieren geändert – neu platzieren`, `G-Code Zeile N: …`, `Motiv … liegt außerhalb …`, `Zeile N: Die erste Laserbahn beginnt an einer unbekannten Kopfposition – davor mit G0 X… Y… (Laser aus) an ihren Startpunkt fahren.` (gilt auch für Upload, `autorun` und Warteschlange: vor der ersten Bahn mit S>0 muss eine absolute X/Y-Fahrt oder G28 stehen; bei `autorun` zählt das G28 der Datei nicht, es entfällt) |
| Fehler (Lauf) | `job.state = "error"` + `job.error`; Laser aus, Parken ohne M112. Scheitert das, M112. ⚠ Hardware |

#### `op=autorun` (automatischer Auftrag)

Der Hauptweg aller Apps (Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md`
Abschnitt 4): Auftrag in Maschinenkoordinaten **ohne Z** hochladen, dann
`autorun`. Wie `start`, plus:

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `x`, `y` | number, optional | nur diesen einen Punkt abtasten (30..390 / 30..370); Standard = Raster über den Motivbereichen |

| | |
| --- | --- |
| Vorbedingungen | wie `start`, aber **nicht referenziert nötig**; Tasterversatz gesetzt (`X/Y-Tasterversatz zuerst unter Fokus & Taster eintragen`) |
| Planung (vor jeder Bewegung) | `G28`/`G30`/`M2` aus der Datei entfallen. Motivbereiche = Laserwege (G1 mit S>0) in 5-mm-Zellen, Teile mit < 10 mm Abstand bilden einen Bereich, Bereich = Umriss + 2 mm (max. 12 Bereiche, sonst einer). Raster je Bereich 1×1 bis 4×4 (ca. ein Punkt je 90 mm, 5 mm vom Rand), höchstens 36 Punkte je Auftrag. Erreichbar ist ein Punkt, wenn der Kopf (Punkt − Tasterversatz) in X10..380 / Y10..360 liegt (Marlin `PROBING_MARGIN` 10 mm; der Laser ist aus, der Kopf darf dafür in die Safezone). Ein Punkt im Randstreifen, den der Taster nie erreicht (er sitzt neben dem Laser), wird am **nächsten erreichbaren Ort höchstens 40 mm daneben** abgetastet; dessen Höhe gilt für den Punkt (`HeightGrid.probe_at`). So lassen sich Motive bis an den Rand des Arbeitsbereichs lasern. Was auch so nicht erreichbar ist, wird aus Nachbarn ergänzt; ein ganz unerreichbarer Bereich bekommt die höchste gemessene Oberfläche. Höhenkorrektur einmal gegen eine ebene Testfläche, damit Bögen/relative X/Y sofort abgelehnt werden. |
| Ablauf | 1. `homing` nur wenn `homed` false ist (nach Verbinden, Reset, Not-Aus). 2. `probing`: je Punkt `G0 X Y` und `G30 E0` (eine Messung, Taster bleibt ausgefahren, kein 16-mm-Anheben durch Marlin), dazwischen nur Hub auf höchste Oberfläche des Bereichs + 3 mm; zwischen Bereichen Z-Rückzug. Der **tiefste Punkt wird zuletzt nochmal** angetastet, `workpiece_surface_z` = tiefster Kontakt, dann `M402` (Taster verstauen) und Z-Rückzug. 3. Höhenkorrektur auf dem Pi (`focus_compensation.py`): Z = Oberfläche + `focus_gap_mm` − `z_switch_tip_offset_mm`, nie unter Oberfläche + 2 mm, Laserlinien in ≤ 2-mm-Stücke, Leerfahrten erst hoch, am Ziel runter, `G91`/`G0 Z-…`/`G90` als Versatz, Vorschub sinkt, wenn Z (9 mm/s) nicht folgt. Ein Auftrag mit **eigenem absolutem Z** wird nur abgetastet, nicht nochmal korrigiert. 4. `running`: Startmelodie, lasern, parken, Melodie. |
| Status | `job.state`: `homing` → `probing` → `running` → `complete`; `job.probe` = `{done, total}` (total = Punkte + 1 Nachmessung) |
| Erfolg | 200 `Automatischer Ablauf gestartet: [Referenzieren → ]Abtasten (N Punkte) → Höhenkorrektur → <name> → Parken` (bzw. `eigenes Z des Auftrags`) |
| Fehler (Start) | 400 `Auftrag ohne Laserbahnen: nichts abzutasten`, `Kein Abtastpunkt erreichbar: …`, `Zeile N: Bögen (G2/G3) – in der App als Linien ausgeben`, `Zeile N: relative X/Y-Fahrten (G91) …`, `Fokushöhe läge näher als 2 mm …`, `Fokus-Absenkung führt unter Oberfläche + 2 mm` |
| Relatives Z | `G91`/`G0 Z-…`/`G90` (Fokus-Absenkung je Durchgang) wird nur hier und in der Warteschlange (Auftrag ohne eigenes Z) als Versatz auf die Kartenhöhe gerechnet, höchstens bis Oberfläche + 2 mm. Bei `op=start` und bei Aufträgen mit eigenem Z gehen die Zeilen unverändert an Marlin. |
| Abbruch / Not-Aus | `op=abort` wirkt in jeder Phase: `homing` nach der X/Y-Referenzfahrt (Kopf steht dann in der Parkecke X0/Y0, Z unverändert, Maschine nicht referenziert), `probing` vor jedem Punkt (Taster wird mit `M402` verstaut), `focusing` alle 500 Zeilen, `running` vor jeder Zeile, `finishing`/`parking` nach dem Parken. Danach `M5 I` und Parken ohne M112, `job.state = aborted`, `job.error = Abgebrochen`. Zwischen allen Phasen ist der Laser aus (`M5 I`). `op=estop` (M112) wirkt sofort. ⚠ Hardware |
| Fehler (Lauf) | `job.state = error`, `job.error` ein Satz mit nächstem Schritt, z. B. `Der Taster hat bei X… Y… kein Material gefunden – Material unter das Motiv legen oder den Tasterversatz prüfen, dann neu starten.`, `Der Taster war bei X… Y… schon gedrückt – Taster und Kabel prüfen, dann neu starten.`, `Abtasten bei X… Y… fehlgeschlagen (…) – Taster prüfen, dann neu starten.`, `Verbindung zur Steuerung unterbrochen (…) – USB-Kabel prüfen, dann neu starten.`; danach Laser aus und Parken (ohne M112). ⚠ Hardware |

#### `op=abort`

| | |
| --- | --- |
| Parameter | keine; **keine** `local_owner()`-Prüfung |
| Wirkung | setzt `stop_job`. Rahmen: stoppt an der nächsten Ecke. Warteschlange (`running`/`pausing`): laufender Auftrag bricht ab, Warteschlange → `stopped`, Rest bleibt `queued`. Einzelauftrag: bricht vor der nächsten Zeile ab, dann `M5 I` und Parken (bereits gepufferte Segmente laufen noch zu Ende, ⚠ Hardware). |
| Erfolg | 200 `Rahmen-Abbruch angefordert: stoppt an der nächsten Ecke, Laser bleibt aus` / `Abbruch angefordert: Laser aus, Parkposition, Warteschlange hält an` / `Abbruch angefordert: Laser aus, danach Parkposition` |
| Fehler | 400 `Kein laufender Auftrag` |
| Hinweis | „angefordert“: Ende über `job.state`/`frame.state` = `aborted` beobachten. Kein Abbruch für LightBurn (dort in LightBurn stoppen oder E-Stop). |

#### `op=frame` (Rahmenfahrt, Laser aus)

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `gcode` | string | Rahmenprogramm, max. 64 KB, max. 2000 Fahrbewegungen. Erlaubt nur `G0`/`G1` mit X/Y (optional `F` 60..9000, `S0`), sowie `G21`, `G90`, `M5`, `M5 I`, `M400`. Punkte in X0..390 / Y0..370. Kein Z, keine Bögen, kein M3, kein G91. |
| `mode` | string | `box` (Rechteck, Standard) oder `hull` (Gummiband) – nur Anzeige/Status, die Bahn liefert der Client |
| `placement` | string, optional | `1`: Rahmen um den Versatz der gespeicherten Platzierung verschieben |
| `name` | string | mit `placement=1`: Datei der Platzierung (leer = beliebige aktive Platzierung) |

| | |
| --- | --- |
| Vorbedingungen | **frei**, kein Riegel (`Notstopp aktiv – erst quittieren`), **referenziert** (`Vor dem Rahmen referenzieren`), **freigegeben** |
| Wirkung | asynchron unter Besitzer `frame`: `M5 I`, `G90`, jede Zeile + `M400` nach jeder Kante, am Ende `M5 I`. Prüft vor jeder Zeile, dass der Laser nicht scharf ist. Gespeicherter Auftrag und `job`-Status bleiben unberührt. |
| Erfolg | 200 `{"message": "Rahmenfahrt gestartet (Rechteck, Laser aus)", "frame": {…}}` |
| Fehler | 400 `Rahmenprogramm fehlt (Feld gcode)`, `Rahmenprogramm zu groß (max. 64 KB)`, `Rahmen Zeile N: im Rahmen nur G0/G1 X/Y (S0), G21, G90, M5 I, M400`, `… Laserleistung im Rahmen verboten (nur S0)`, `… Punkt außerhalb X0..390 / Y0..370`, `… Vorschub außerhalb 60..9000 mm/min`, `Rahmen enthält keine Fahrbewegung`, `Rahmen mit mehr als 2000 Fahrbewegungen`, `Rahmenart muss box oder hull sein`, `Ein Auftrag oder Rahmen läuft bereits` |

Die Web-UI muss das Rahmenprogramm selbst erzeugen, z. B. ein Rechteck aus
`GET /api/jobs/<name>/geometry` → `bounds` (Laserbahnen, nach Platzierung
`origin.placement.bounds`):

```text
G21
G90
G0 X<xmin> Y<ymin> F6000
G0 X<xmax> Y<ymin>
G0 X<xmax> Y<ymax>
G0 X<xmin> Y<ymax>
G0 X<xmin> Y<ymin>
```

### 4.8 `POST /api/action` – Warteschlange

Im Speicher, **nicht dauerhaft**: ein Dienst-Neustart leert sie. Max. 50
Einträge. Platzierung und Datei-SHA werden beim Einreihen eingefroren.

#### `op=queue_add`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `name` | string | gespeicherte Auftragsdatei |
| `origin` / `anchor` | string, optional | wie `op=place` (Standard `absolute` / `tr`) |
| `placement` | string, optional | `1` = gespeicherte Platzierung übernehmen |

| | |
| --- | --- |
| Vorbedingungen | Freigabe (Wächter-Prüfung); nur bei `origin=current` **frei** (frisches M114); bei `current`/`user` **referenziert**. Geht auch, während die Warteschlange läuft. |
| Erfolg | 200 `{"message": "Eingereiht: <name> (#<id>, <origin>)", "queue": {…}}` |
| Fehler | 400 `Warteschlange voll (max. 50 Einträge)` + alle Platzierungsfehler aus 4.6 |

#### `op=queue_run`

| | |
| --- | --- |
| Parameter | keine |
| Vorbedingungen | **frei**, Tasterversatz gesetzt; jeder `queued`-Eintrag wird vorab wie `autorun` geplant, sonst 400 `Warteschlange #<id> (<datei>): <Grund>` und nichts bewegt sich; nicht schon aktiv (`Warteschlange läuft bereits`), mindestens ein `queued` (`Keine wartenden Aufträge in der Warteschlange`), kein Auftrag/Rahmen (`Ein Auftrag oder Rahmen läuft bereits`) |
| Wirkung | asynchron unter Besitzer `job`: arbeitet alle `queued` der Reihe nach ab, jeder durch denselben automatischen Ablauf wie `op=autorun`: referenzieren nur wenn nötig, abtasten (`job.probe`), Höhenkorrektur inkl. relativer Fokus-Absenkungen, lasern, parken; Laser aus zwischen den Phasen und Aufträgen. Vor jedem Eintrag erneute Prüfung (Datei vorhanden, SHA gleich, Grenzen, Wächter). Erster Fehler/Abbruch → Eintrag `error`/`aborted`, Warteschlange `stopped`. Setzt nach `paused`/`stopped` fort. |
| Erfolg | 200 `{"message": "Warteschlange gestartet: N Auftrag/Aufträge", "queue": {…}}` |
| Fehler (Lauf) | `job.error` am Eintrag (`items[].error`), z. B. Abtastfehler |

#### `op=queue_pause`

Keine Parameter. Nur wenn `queue.state == "running"` (sonst 400 `Warteschlange
läuft nicht`). Hält **nach** dem laufenden Auftrag an (`pausing` → `paused`);
kein Vorschub-Halt mitten im Auftrag. Fortsetzen mit `queue_run`.
200 `{"message": "Warteschlange hält nach dem laufenden Auftrag an", "queue": {…}}`.

#### `op=queue_skip` / `op=queue_remove`

| Parameter | Typ | Erlaubt |
| --- | --- | --- |
| `id` | int | `queue.items[].id` |

| | |
| --- | --- |
| Vorbedingungen | keine Besitzer-Prüfung; Eintrag nicht `running` (`Laufender Auftrag: zuerst abbrechen`); `queue_skip` nur für `queued` (`Nur wartende Aufträge können übersprungen werden`) |
| Wirkung | `skip`: Eintrag → `skipped` (bleibt sichtbar, kann nicht zurückgeholt werden); `remove`: Eintrag entfernt |
| Erfolg | 200 `{"message": "Übersprungen: <file> (#id)" / "Entfernt: <file> (#id)", "queue": {…}}` |
| Fehler | 400 `Warteschlangen-Eintrag fehlt (Feld id)`, `Warteschlangen-Eintrag N nicht gefunden` |

#### `op=queue_clear`

Keine Parameter, keine Vorbedingung. Entfernt alle Einträge außer dem
laufenden. 200 `{"message": "Warteschlange geleert", "queue": {…}}`.

### 4.9 `POST /api/settings`

Form-Felder (**alle drei Zahlen Pflicht**, kein Teil-Update):

| Feld | Typ | Bereich |
| --- | --- | --- |
| `z_clearance_mm` | number | 0.5..50 |
| `focus_gap_mm` | number | 0.1..30 |
| `z_switch_tip_offset_mm` | number | -20..20 |
| `probe_offset_x_mm`, `probe_offset_y_mm` | number oder leer | -80..80; beide oder keiner (leer = Versatz löschen) |

| | |
| --- | --- |
| Vorbedingungen | keine Besitzer-Prüfung (geht auch mit LightBurn); sendet nichts an das SKR |
| Sperre | nimmt die Maschinensperre **blockierend** → wartet, bis eine laufende Web-Fahrt (Homing usw.) fertig ist |
| Wirkung | speichert dauerhaft (`config.json`), löscht die gemessene Werkstückoberfläche (`workpiece_surface_z = null`) |
| Erfolg | 200 `{message, z_clearance_mm, focus_gap_mm, z_switch_tip_offset_mm, probe_offset_x_mm, probe_offset_y_mm, note}` |
| Fehler | 400 `Z-Rückzug muss zwischen 0,5 und 50 mm liegen`, `Fokusabstand muss zwischen 0,1 und 30 mm liegen`, `Schalter-zu-Spitze-Offset muss zwischen -20 und +20 mm liegen`, `Taster-X/Y-Versatz muss -80..80 mm sein`, `X/Y-Tasterversatz entweder beide eintragen oder beide leer lassen` |

### 4.10 `POST /api/commission`

| Feld | Wert |
| --- | --- |
| `confirm` | exakt `TESTS_BESTANDEN_LASER_GETRENNT` |
| `enable` | `1` (freigeben) oder `0` (sperren) |

Vorbedingung: Besitzer frei (`LightBurn/Job trennen vor Hardwarefreigabe`).
Speichert `validated` dauerhaft. 200 `{"message": "Test-Freigabe aktiviert|gesperrt",
"hardware_electrically_verified": false}`. Fehler: 400 `Zuerst die
dokumentierten Prüfungen ohne Laser durchführen`, `enable 0/1 erwartet`.
Die Freigabe ist **keine** elektrische Sicherheitsprüfung; die UI muss das
deutlich sagen und `enable=1` nur nach bewusster Bestätigung senden.

### 4.11 `POST /api/firmware`

| | |
| --- | --- |
| Anfrage | multipart, Feld `file` = `firmware.bin` |
| Prüfung des Abbilds | 32 KB .. 228 KB (`0x08040000 − 0x08007000`), gültiger Vektor für BTT-Bootloader (Start 0x08007000), enthält `LumaCut CNC` und `Switching to Binary Protocol` |
| Vorbedingungen | **frei**, kein Auftrag (`Während eines Auftrags wird nicht geflasht`), aktuelle Firmware `firmware_upload_supported` (sonst 400 `Aktuelle SKR-Firmware kann keine Dateien empfangen: einmalig per SD-Karte eine Firmware mit Pi-Update flashen`) |
| Wirkung | asynchron (Thread), Besitzer `firmware`: Laser/24-V-Schiene/Zubehör aus, SD-Karte prüfen, Upload, `M997`, Neustart, Warten bis M115 den neuen Build meldet (bis 120 s). Fortschritt **nur** über `/api/status` → `firmware_update`. Danach nicht referenziert. ⚠ Hardware |
| Erfolg | 200 `Firmware-Update gestartet (N KB, Build …). SKR startet gleich neu.` |
| Fehler (sofort) | 400 `firmware.bin auswählen`, `Dateigröße … unplausibel …`, `Keine SKR-Mini-MZ-Firmware für den BTT-Bootloader …`, `LumaCut-Kennung fehlt: fremde Firmware wird nicht geflasht`, `Firmware ohne BINARY_FILE_TRANSFER: …` |
| Fehler (Lauf) | `firmware_update.state = "error"`, `message` z. B. `Keine SD-Karte im SKR erkannt (M21): …`, `SKR nach dem Flashen nicht wieder erreichbar: …` |

### 4.12 Aufträge (Dateien)

#### `POST /api/upload`

| | |
| --- | --- |
| Anfrage | multipart, Feld `file`; Dateiname ohne Pfad, Endung `.gcode`, `.gc`, `.nc`; UTF-8; max. 32 MB |
| Vorbedingungen | **freigegeben** (`Mechanik noch nicht freigegeben`); keine Besitzer-Prüfung (Upload während eines Auftrags möglich) |
| Prüfung | jede Zeile durch den G-Code-Wächter (`G-Code Zeile N: …`), nicht leer (`G-Code ist leer`), Laserbahnen in X30..390 / Y30..370 (`Motiv X… liegt außerhalb … (30-mm-Safezone)`) |
| Wirkung | atomar speichern (`<name>.partial` → `<name>`), **überschreibt** gleichnamige Datei, verwirft deren Platzierung. Ein eingereihter Auftrag mit gleichem Namen scheitert danach am SHA-Vergleich. |
| Erfolg | 200 `Marlin-Auftrag geprüft und gespeichert: <name>` |
| Fehler | 400 `G-Code-Datei auswählen`, `Nur .gcode, .gc oder .nc Dateien`; Nicht-UTF-8 → 400 Python-Text; >32 MB → **413 HTML** |

#### `GET /api/jobs`

200 `{"files": [{"name": "a.gcode", "bytes": 1234, "modified": 1761475200}]}`
(alphabetisch, nur `.gcode`/`.gc`/`.nc`; `modified` = Unix-Sekunden).

#### `GET /api/jobs/<name>/content`

200 `text/plain; charset=utf-8` mit dem G-Code. Fehler 400 `Unzulässiger
Dateiname`, `Auftrag nicht gefunden` (JSON).

#### `POST /api/jobs/<name>/delete`

Kein Body. Vorbedingungen: nicht der laufende Auftrag (`Laufender Auftrag
kann nicht gelöscht werden`), nicht `queued`/`running` in der Warteschlange
(`Auftrag steht in der Warteschlange – zuerst dort entfernen`). Verwirft
die Platzierung der Datei. 200 `Auftrag gelöscht: <name>`.

#### `GET /api/jobs/<name>/geometry`

200:

```json
{"bounds": {"xmin": 40.0, "ymin": 40.0, "xmax": 120.0, "ymax": 90.0},
 "segments": 152,
 "center": [80.0, 65.0],
 "probe_candidates": [[45.0, 45.0], [65.0, 45.0]],
 "warning": "Rasterpunkte sind Kandidaten: Materialabdeckung noch nicht vermessen."}
```

`bounds` = Hülle der **Laserbahnen** (nicht der Leerfahrten), absolute
Koordinaten aus der Datei (ohne Platzierung). `probe_candidates`: Raster
20 mm, 5 mm Rand, max. 100 Punkte. Fehler 400 (englisch aus `smart_cam`):
`Line N: G2/G3 arc geometry needs dedicated analyzer`, `No powered
vector/raster motion found; cannot infer motif bounds`, `Too many sampling
points; choose coarser grid`; `Unzulässiger Dateiname`, `Auftrag nicht
gefunden`. Prüft die Dateiendung nicht (anders als `content`/`delete`).

### 4.13 Kamera

#### `GET /api/camera/snapshot?w=<px>&h=<px>`

| Parameter | Typ | Bereich | Standard |
| --- | --- | --- | --- |
| `w` | int (Query) | 160..4096 | 1280 |
| `h` | int (Query) | 120..3072 | 960 |

Bewegt nie etwas, keine Vorbedingung. Startet `ffmpeg` (V4L2), verwirft 5
Bilder für die Belichtung, liefert das nächste als `image/jpeg`. Dauer
typisch 1–3 s, Timeout 15 s. ⚠ Hardware. Fehler: 503 `Keine Kamera an
/dev/video0 (LUMACUT_CAMERA in /etc/lumacut/lumacut.env)`, `Kamera antwortet
nicht: …`, `Kamera lieferte kein Bild: …`; 400 `Bildgröße unzulässig`.
Parallele Anfragen konkurrieren um dasselbe Gerät → nie gleichzeitig
anfordern, keine Bildrate erwarten.

#### `GET /api/camera/calibration`

200 JSON: `image_width`, `image_height`, `px_per_mm`, `scan_z`, `offset_mm`
[x, y], `rotation_deg`, `flip_x`, `flip_y` (±1), `crop_fraction`,
`camera_matrix`, `dist_coeffs`, `exposure`, `homography` (je null oder
Werte), `android` (null oder das Kameramodell der Tablet-App unverändert:
`photoWidth`, `photoHeight`, `scanZ` und `lens` aus dem Punktraster oder vier
Punkte `photo`/`relMm`; der Pi prüft nur die Form), `calibrated`, `notes`, `updated_by`, `revision` (0 = nie
gespeichert), `updated_at`, `format` (`lumacut-camera-calibration/1`),
`schema_version` (1), `placeholder` (true = Standardwerte, keine Messung),
`status` (`platzhalter`, `kalibriert`, `unkalibriert`), `storage` `{path,
write_path, writable, error}`.

#### `PUT /api/camera/calibration`

| | |
| --- | --- |
| Anfrage | `Content-Type: application/json`, Objekt mit den Feldern oben plus Pflichtfeld `revision` (die zuletzt gelesene) |
| Bereiche | `image_width` 160..8192, `image_height` 120..8192, `px_per_mm` 0.5..100, `scan_z` 0..90, `rotation_deg` -180..180, `crop_fraction` 0..<0.4, `offset_mm` je ±200, `notes` ≤2000 Zeichen, `updated_by` ≤80 |
| Erfolg | 200 gespeicherte Kalibrierung + `message`, `revision` +1 |
| Fehler | **403** `Fremde Webseite darf die Kalibrierung nicht ändern` (Origin ≠ Host), **415** `Content-Type application/json erwartet`, **413** `Kalibrierung zu groß (max. 64 KB)`, **409** `Kalibrierung wurde inzwischen geändert …` + `current` (aktuelle Daten), 400 `revision fehlt: …`, `Kalibrierung ungültig: …`, `Unbekannte Felder: …` |

### 4.14 Material-Datenbank

Eine Liste für alle Programme (Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md`
Abschnitt 3), gespeichert in `/var/lib/lumacut/materials.json`
(`$LUMACUT_DATA/materials.json`), atomar geschrieben (temporäre Datei, fsync,
`os.replace`). Beim ersten Start legt der Pi die Startwerte an (`builtin: true`,
Revision 1). Jede Änderung erhöht `revision` um 1. Ist die Datei kaputt, wird
sie als `materials.corrupt` aufbewahrt und die Startwerte kommen zurück.

Material (JSON):

| Feld | Typ | Bereich |
| --- | --- | --- |
| `id` | string | vom Pi vergeben (UUID) |
| `name` | string | 1..80 Zeichen |
| `thickness_mm` | number | 0..50 |
| `process` | string | `Schneiden`, `Gravieren`, `Markieren` |
| `mode` | string | `line`, `fill` |
| `power_pct` | number | 0..100 |
| `speed_mm_min` | number | 1..6000 |
| `passes` | int | 1..30 (Standard 1) |
| `interval_mm` | number | 0.01..5 (Standard 0.1) |
| `depth_per_pass_mm` | number | 0..50 (Standard 0); > 0: Durchgänge = aufgerundet Dicke / Tiefe |
| `z_step_mm` | number | 0..2 (Standard 0); (Durchgänge − 1) × `z_step_mm` ≤ 3 mm |
| `builtin` | bool | vom Pi gesetzt (Startwert), bleibt beim Ändern erhalten |
| `updated` | string | vom Pi gesetzt, UTC `2026-10-26T15:00:00Z` |
| weitere Felder | beliebig (JSON) | werden unverändert gespeichert und zurückgegeben (z. B. Studio `material_id`, `laser_id`, `notes`); höchstens 32 Felder, zusammen 16 KB |

| Anfrage | Erfolg (200) |
| --- | --- |
| `GET /api/materials` | `{"revision": n, "materials": [Material, …]}` |
| `POST /api/materials`, JSON = Material ohne `id` + `base_revision` | `{"revision": n+1, "material": Material}` |
| `PUT /api/materials/<id>`, JSON = geänderte Felder + `base_revision` (fehlende Felder bleiben) | `{"revision": n+1, "material": Material}` |
| `DELETE /api/materials/<id>?base_revision=n` | `{"revision": n+1}` |

Fehler: **409** `{"error": "Materialliste wurde inzwischen geändert (Revision n) – neu laden und erneut versuchen", "revision": n}`
bei veralteter `base_revision` (neu laden, erneut versuchen); **404**
`Material nicht gefunden`; 400 `base_revision fehlt`, `JSON-Objekt erwartet …`,
`power_pct muss zwischen 0 und 100 liegen` usw. Die Apps halten nur einen
Zwischenspeicher für den Fall ohne Verbindung.

### 4.15 Android-App-Updates

Die Android-CI veröffentlicht jede mit dem festen Schlüssel signierte APK als GitHub-Release
(Tag `android-1.0.<n>`, Assets `LumaCut-Android.apk` und `LumaCut-Android.json`). Der Pi holt
die neueste Version selbst: ca. 30 s nach dem Start, danach alle 6 h (nicht während eines
Auftrags) und auf `op=app_update_check`. Er prüft Größe und SHA-256 und behält genau eine APK
(`/var/lib/lumacut/marlin/app/`). Die Maschine wird dabei nie angesprochen. Android installiert
nur eine APK mit demselben Signaturschlüssel wie die installierte App.

#### `GET /api/app/android`

| | |
| --- | --- |
| Erfolg | 200 `{"available": true, "version_code": 52, "version_name": "1.0.52", "sha256": "…", "size": 9876543, "checked_at": "2026-10-27T08:00:00Z", "error": null}`; ohne gespeicherte APK `available: false` und `version_*` = `null` |

#### `GET /api/app/android.apk`

| | |
| --- | --- |
| Erfolg | 200, `application/vnd.android.package-archive`, Datei `LumaCut.apk` |
| Fehler | 404 `Keine App-Version auf dem Pi – …` |

#### `op=app_update_check`

Keine Parameter, **keine** Vorbedingung (nur Netzwerk). Prüft das neueste GitHub-Release
sofort und lädt eine neuere APK.

| | |
| --- | --- |
| Erfolg | 200 `{"message": "App-Version 1.0.52 auf dem Pi bereit", …Felder wie oben}` |
| Fehler | 503 `{"error": "App-Update: <Grund>", …}` (z. B. kein Internet, Prüfsumme falsch); eine schon vorhandene APK bleibt erhalten |

---

## 5. Polling-Empfehlung

- `/api/status` alle **1–2 s** (alte UI: 1,8 s). Während `activity != "idle"`
  oder `owner != "Frei"` gern 0,5–1 s; im Hintergrund-Tab (Page Visibility)
  auf 5–10 s drosseln.
- Nie überlappend pollen: nächste Anfrage erst nach Antwort oder Timeout
  (Status-Timeout 3 s; der Server antwortet nach spätestens ~0,25 s plus
  Netz).
- `busy: true` ist **normal** während Fahrten. Live-Felder (Besitzer, Riegel,
  Laser, referenziert) gelten; übrige Werte als „Stand vor `stale_ms` ms“
  kennzeichnen (z. B. dezent ausgrauen), nicht als Fehler melden.
- `busy: true` mit `stale_ms: null`: es gibt noch keinen vollständigen
  Status → fehlende Felder als „unbekannt“ anzeigen.
- Netzfehler/Timeout: nach 2–3 Fehlversuchen „Pi nicht erreichbar“ anzeigen,
  Bedienelemente außer E-Stop sperren, weiter pollen (Backoff bis 5 s).
- `/api/jobs` nur bei Bedarf (nach Upload/Löschen, beim Öffnen der Liste) oder
  alle 10–15 s; `/api/camera/calibration` nur beim Öffnen der Kamera-Ansicht.
- Kein Server-Push (kein WebSocket/SSE): Fortschritt nur per Polling.

---

## 6. Sicherheitsmodell für UIs

1. **E-Stop immer erreichbar**: fest sichtbar (nicht scrollend, nicht in
   Menüs), nie deaktiviert – auch bei `busy`, fremdem Besitzer, Offline und
   während Modals. `op=estop` braucht keine Vorbedingung. Sofort senden (eine
   Bestätigung ist beim Not-Aus **nicht** angebracht; die alte UI fragt per
   `confirm()` – das verzögert). Bei Netzfehler/5xx wiederholen (Abschnitt
   9.2). Software-E-Stop ersetzt den physischen Not-Aus nicht; UI-Hinweis.
2. **Riegel aktiv** (`emergency_latched`): alles außer E-Stop und „Notstopp
   quittieren“ sperren; Anleitung „SKR zurücksetzen, dann quittieren, dann
   referenzieren“ anzeigen, `fault` zeigen.
3. **Bestätigungen** (bewusster Dialog) vor: `start`, `autorun`, `queue_run`
   (Laser schneidet!), `/api/firmware`, `/api/commission enable=1`,
   `/api/jobs/<name>/delete`, `queue_clear`, `/api/settings` (löscht die
   gemessene Oberfläche), `origin_clear`. Ohne Bestätigung: `abort`, `park`,
   `jog`, `frame`, `moveto`, `home` (Hinweis auf freie 30-mm-Zone ist
   sinnvoll), Abfragen.
4. **Jog-Schritte**: nur `0.1`, `1`, `10` mm mit Vorzeichen anbieten – andere
   Werte lehnt der Pi ab. Z-Jog deutlich getrennt (F360). Kein Dauer-Jog;
   nächsten Schritt erst nach Antwort senden (Taste sperren, solange die
   Anfrage läuft).
5. **Sperrmatrix** (Bedingung → gesperrt):

| Bedingung | Sperren |
| --- | --- |
| nicht `connected` | alles außer E-Stop, `connect`, Upload, Dateiliste, Einstellungen |
| `owner != "Frei"` (inkl. `lightburn`, `firmware`) | alle Bewegungen, Zubehör, `start`/`autorun`/`queue_run`, `frame`, `place`, `origin_set`, Firmware, Freigabe; Anzeige „belegt durch …“ |
| `activity == "job"` | wie oben; **erlaubt**: E-Stop, `abort`, `queue_pause` (wenn `running`), `queue_add`/`skip`/`remove`/`clear`, Upload, Einstellungen (mit Vorsicht) |
| `activity == "framing"` | wie oben; erlaubt: E-Stop, `abort` |
| `firmware_update.state` ∈ `uploading`, `rebooting` | alles außer E-Stop |
| nicht `homed` | `jog`, `park`, `moveto`, `probe`, `frame`, `start`, `origin_set`, Platzierung `current`/`user` (`autorun`, `queue_run` und `home` bleiben) |
| nicht `config.validated` | `home`, `jog`, Fahrten, `frame`, `start`/`autorun`/`queue_run`, Upload |
| `probe_xy_offset_mm == null` | `probe`, `autorun` |
| `z_probe_supported == false` | `probe`, `autorun` |
| nicht `firmware_upload_supported` | Firmware-Upload |
| `state == "Busy"` | Aktionen mit „frei“ kurz sperren (Server lehnt sonst ab) |

6. **Laser**: Der Laser ist nur in einem Auftrag an; `laser_armed == true`
   außerhalb von `activity == "job"` ist ein Fehlerzustand → deutlich warnen,
   E-Stop anbieten.
7. **Doppelklick-Schutz**: Aktionsknöpfe während der laufenden Anfrage
   sperren; Server lehnt Doppelstarts zwar ab, aber Meldungen verwirren.
8. **Fehlertexte** aus `error` unverändert anzeigen (sie sind deutsch und
   für Nutzer formuliert).

---

## 7. Authentifizierung, CORS, Same-Origin

### 7.1 `X-LumaCut-Key` wird nicht geprüft

Der Pi prüft **keinen** Schlüssel (bewusst, siehe
[PI_STATUS_UND_OFFENE_PUNKTE.md](PI_STATUS_UND_OFFENE_PUNKTE.md); die Web-UI
zeigt „Keine Anmeldung erforderlich“). Studio schickt `X-LumaCut-Key`
trotzdem, wenn ein Schlüssel eingestellt ist; der Pi ignoriert den Header.
Wer ihn mitsenden will (für eine spätere Prüfung):

```js
fetch("/api/status", {headers: {"X-LumaCut-Key": key}})
```

```sh
curl -H "X-LumaCut-Key: $LUMACUT_KEY" http://lumacut.local:8080/api/status
```

Den Schlüssel nie in Quelltext, Logs oder URLs schreiben. Achtung: ein
eigener Header macht Cross-Origin-Anfragen „nicht einfach“ (Preflight,
siehe 7.2) – auf derselben Origin kein Problem.

Schutz liegt allein im Netz: WLAN schützen, Port 8080 und 23 nicht ins
Internet freigeben. Kein HTTPS.

### 7.2 CORS / Same-Origin

- Der Pi sendet **keine** `Access-Control-Allow-*`-Header. `OPTIONS` antwortet
  200 ohne CORS-Header.
- Folge: Eine Web-UI muss **vom Pi selbst** ausgeliefert werden (`GET /`,
  relative URLs wie `/api/status`). Von einer anderen Origin (z. B.
  Vite-Dev-Server auf dem Laptop) kann der Browser Antworten nicht lesen und
  Anfragen mit Preflight (JSON, eigene Header) nicht senden. Für die
  Entwicklung einen Dev-Proxy verwenden (`/api` → `http://lumacut.local:8080`).
- Native Clients (Studio, curl, Tablet-App) sind von CORS nicht betroffen.
- **CSRF-Lücke**: „Einfache“ Formular-POSTs (`application/x-www-form-urlencoded`,
  `multipart/form-data`) an `/api/action`, `/api/upload`, `/api/settings`,
  `/api/commission`, `/api/firmware` werden **auch mit fremdem `Origin`
  ausgeführt** (nachgeprüft mit dem Testclient). Eine beliebige Webseite im
  Browser eines Nutzers im selben WLAN könnte also Aktionen auslösen. Nur
  `PUT /api/camera/calibration` prüft `Origin`. Siehe Abschnitt 10.

---

## 8. Veralteten Pi erkennen

Es gibt **kein** Versions- oder Commit-Feld. Erkennung über vorhandene
Felder/Antworten (Commit = erster Commit auf main mit der Funktion):

| Funktion | Erkennbar an | seit |
| --- | --- | --- |
| Firmware-Update über den Pi | `firmware_update` in `/api/status` | 62f47a1 |
| `op=park`, `/api/jobs/<name>/content` | `op=park` nicht 400 `Unbekannte Marlin-Aktion: park` | 5d3b0ea |
| `op=moveto`, Kamera-Snapshot | `camera` in `/api/status` | 2c61b8a |
| Kamera-Kalibrierung | `GET /api/camera/calibration` nicht 404 | 95ace5e |
| Rahmenfahrt | `frame` und `activity` in `/api/status` | 65a22b4 |
| nicht blockierender Status | `busy`, `stale_ms` in `/api/status` | fb2f458 |
| Ursprung/Platzierung | `origin` in `/api/status` | ed96c63 |
| Warteschlange | `queue` in `/api/status` | e7166c3 |
| Streaming | `stream_window`, `streamed_count` in `/api/status` | 22ece4f |

Empfehlung für die UI: beim Start einmal `/api/status` lesen, fehlende Felder
→ Funktion ausblenden und Hinweis „Pi-Dienst veraltet: auf dem Pi
`sudo bash /opt/lumacut/pi400/update.sh` ausführen“ (siehe
[PI_BETRIEB.md](PI_BETRIEB.md)). Ein unbekanntes `op` liefert 400 `Unbekannte
Marlin-Aktion: <op>`, ein unbekannter Pfad 404 (HTML).

Da die neue UI als `index.html` mit dem Pi-Dienst ausgeliefert wird, passen UI
und API nach einem Update zusammen; die Prüfung schützt vor einem Browser-
Cache nur bedingt (`Cache-Control: no-store` ist gesetzt).

---

## 9. Beispiele

### 9.1 curl

```sh
PI=http://lumacut.local:8080
A="$PI/api/action"

# Status
curl -s "$PI/api/status"

# Not-Aus und Quittieren
curl -s -X POST "$A" -d op=estop
curl -s -X POST "$A" -d op=estop_reset

# Verbindung und Abfragen
curl -s -X POST "$A" -d op=connect
curl -s -X POST "$A" -d op=info
curl -s -X POST "$A" -d op=position
curl -s -X POST "$A" -d op=endstops

# Bewegung (synchron, langer Timeout)
curl -s -m 300 -X POST "$A" -d op=home
curl -s -m 60  -X POST "$A" -d op=jog -d axis=X -d distance=10
curl -s -m 60  -X POST "$A" -d op=jog -d axis=Z -d distance=-0.1
curl -s -m 180 -X POST "$A" -d op=park
curl -s -m 180 -X POST "$A" -d op=moveto -d x=120 -d y=80
curl -s -m 300 -X POST "$A" -d op=probe
curl -s -m 300 -X POST "$A" -d op=probe -d x=100 -d y=100

# Zubehör
curl -s -X POST "$A" -d op=light -d on=1
curl -s -X POST "$A" -d op=exhaust -d on=0

# Ursprung und Platzierung
curl -s -X POST "$A" -d op=origin_set
curl -s -X POST "$A" -d op=origin_set -d x=100 -d y=100
curl -s -X POST "$A" -d op=origin_clear
curl -s -X POST "$A" -d op=place -d name=logo.gcode -d origin=user -d anchor=center
curl -s -X POST "$A" -d op=place_clear

# Aufträge
curl -s -X POST "$A" -d op=start -d name=logo.gcode
curl -s -X POST "$A" -d op=start -d name=logo.gcode -d placement=1
curl -s -X POST "$A" -d op=start -d name=logo.gcode -d origin=current -d anchor=tl
curl -s -X POST "$A" -d op=autorun -d name=logo.gcode
curl -s -X POST "$A" -d op=autorun -d name=logo.gcode -d x=150 -d y=120
curl -s -X POST "$A" -d op=abort

# Rahmen (Laser aus); --data-urlencode wegen Zeilenumbrüchen
curl -s -X POST "$A" -d op=frame -d mode=box --data-urlencode gcode=$'G21\nG90\nG0 X40 Y40 F6000\nG0 X120 Y40\nG0 X120 Y90\nG0 X40 Y90\nG0 X40 Y40'
curl -s -X POST "$A" -d op=frame -d mode=box -d placement=1 -d name=logo.gcode --data-urlencode gcode@rahmen.gcode

# Warteschlange
curl -s -X POST "$A" -d op=queue_add -d name=a.gcode
curl -s -X POST "$A" -d op=queue_add -d name=b.gcode -d origin=user -d anchor=tl
curl -s -X POST "$A" -d op=queue_add -d name=c.gcode -d placement=1
curl -s -X POST "$A" -d op=queue_run
curl -s -X POST "$A" -d op=queue_pause
curl -s -X POST "$A" -d op=queue_skip -d id=2
curl -s -X POST "$A" -d op=queue_remove -d id=3
curl -s -X POST "$A" -d op=queue_clear

# Einstellungen und Freigabe
curl -s -X POST "$PI/api/settings" -d z_clearance_mm=20 -d focus_gap_mm=7 \
  -d z_switch_tip_offset_mm=1.5 -d probe_offset_x_mm=-25 -d probe_offset_y_mm=10
curl -s -X POST "$PI/api/commission" -d confirm=TESTS_BESTANDEN_LASER_GETRENNT -d enable=1

# Dateien
curl -s -F file=@logo.gcode "$PI/api/upload"
curl -s "$PI/api/jobs"
curl -s "$PI/api/jobs/logo.gcode/content"
curl -s "$PI/api/jobs/logo.gcode/geometry"
curl -s -X POST "$PI/api/jobs/logo.gcode/delete"

# Firmware
curl -s -F file=@firmware.bin "$PI/api/firmware"

# Kamera
curl -s -o bild.jpg "$PI/api/camera/snapshot?w=1280&h=960"
curl -s "$PI/api/camera/calibration"
curl -s -X PUT -H 'Content-Type: application/json' \
  -d '{"revision": 0, "px_per_mm": 4.2, "updated_by": "web"}' "$PI/api/camera/calibration"
```

### 9.2 JS-Helfer (`fetch`)

```js
// Same-Origin: relative URLs. Fehler immer als Error mit deutschem Text.
const TIMEOUTS = {status: 3000, quick: 15000, motion: 300000, upload: 120000};
const MOTION_OPS = new Set(["home", "jog", "park", "moveto", "probe",
                            "info", "position", "endstops", "connect", "estop_reset"]);

class PiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, {method = "GET", body = null, timeout = TIMEOUTS.quick} = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let response;
  try {
    // URLSearchParams/FormData setzen Content-Type selbst.
    response = await fetch(path, {method, body, cache: "no-store", signal: ctrl.signal});
  } catch (e) {
    throw new PiError(e.name === "AbortError" ? "Zeitüberschreitung: Pi antwortet nicht"
                                             : "Pi nicht erreichbar", 0);
  } finally {
    clearTimeout(timer);
  }
  const raw = await response.text();          // 404/405/413 kommen als HTML
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch { /* kein JSON */ }
  if (!response.ok) {
    throw new PiError(String(data?.error || data?.message || ("HTTP " + response.status)).slice(0, 400),
                      response.status);
  }
  return data;
}

const status = () => api("/api/status", {timeout: TIMEOUTS.status});

function action(op, fields = {}) {
  const body = new URLSearchParams({...fields, op});
  return api("/api/action", {method: "POST", body,
                             timeout: MOTION_OPS.has(op) ? TIMEOUTS.motion : TIMEOUTS.quick});
}

// E-Stop: sofort, ohne Bestätigung, bei Netzfehler/5xx wiederholen.
// 503 "USB getrennt" bedeutet: Riegel gesetzt, aber M112 NICHT übertragen
// -> physischen Not-Aus anzeigen, trotzdem weiter versuchen.
async function emergencyStop({attempts = 5, delayMs = 300} = {}) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      return await api("/api/action", {method: "POST",
        body: new URLSearchParams({op: "estop"}), timeout: 2000});
    } catch (e) {
      last = e;
      if (e.status && e.status < 500) break;  // 4xx: Wiederholen hilft nicht
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  throw last;  // UI: "PHYSISCHEN NOT-AUS DRÜCKEN"
}

// Beispiele
// await action("jog", {axis: "X", distance: "10"});
// await action("frame", {mode: "box", gcode: lines.join("\n")});
// const fd = new FormData(); fd.append("file", file);
// await api("/api/upload", {method: "POST", body: fd, timeout: TIMEOUTS.upload});
```

### 9.3 Client-Timeouts

| Anfrage | Server-Dauer | Empfohlener Client-Timeout |
| --- | --- | --- |
| `/api/status` | ≤ ~0,3 s | 3 s |
| `estop` | Millisekunden | 2 s (mit Wiederholung) |
| `start`, `autorun`, `queue_*`, `frame`, `abort`, `place`, `origin_*`, `light`, `exhaust` | < 1 s (+ M114 bei `current`) | 15 s |
| `home`, `probe`, `park`, `moveto`, `jog` | Fahrtdauer, Teilschritte bis 150 s | 300 s |
| `info`/`position`/`endstops`, `connect`, `estop_reset` | bis ~12 s | 30 s |
| `/api/settings` | wartet auf laufende Web-Fahrt | 300 s |
| Upload / Firmware | Größe + Prüfung | 120 s |
| Kamera-Snapshot | 1–15 s | 20 s |

Ein Client-Timeout bricht die Fahrt auf dem Pi **nicht** ab. Danach Status
lesen; zum Anhalten E-Stop.

---

## 10. Lücken und Inkonsistenzen (Stand dieser Referenz)

Für das Redesign relevant, Vorschläge in Klammern:

1. **CSRF**: Formular-POSTs von fremden Webseiten werden ausgeführt
   (Abschnitt 7.2). (Origin-Prüfung wie bei der Kalibrierung für alle POSTs:
   `Origin` vorhanden und ≠ Host → 403. Native Clients senden kein `Origin`.)
2. **Kein Push**: nur Polling. (SSE `GET /api/events` mit Status-Diffs.)
3. **Keine Kamera-Vorschau**: nur Einzelbild per ffmpeg (1–3 s). (MJPEG-Stream
   `multipart/x-mixed-replace` oder dauerhafter ffmpeg-Prozess.)
4. **Kein Pausieren/Fortsetzen im Auftrag** (nur `abort`; `queue_pause` erst
   nach dem Auftrag). (M0/Feed-Hold ist bei Marlin heikel; mindestens
   „nach aktueller Zeile anhalten“.)
5. **Kein Abbruch für LightBurn-Sitzungen** außer E-Stop.
6. **Dateien**: kein Umbenennen, kein Download-Name, kein Hochladen ohne
   Mechanik-Freigabe; Upload überschreibt ohne Rückfrage. (`/rename`,
   `overwrite=0`.)
7. **Warteschlange** nicht dauerhaft, nicht umsortierbar, `skipped` nicht
   rücksetzbar. (`queue_move id,to`, `queue_unskip`.)
8. **`job.line`** zählt gesendete, nicht ausgeführte Zeilen; kein
   Zeit-/Restzeitwert. (`started_at`, `elapsed_s`, Schätzung.)
9. **Keine Version** im Status. (`api_version`, `server_commit`.)
10. **Fehlerformat uneinheitlich**: 404/405/413 als HTML; `op=connect` ohne
    USB-Gerät → 500 statt 503; nicht-numerische Felder → englischer
    Python-Text; `geometry` mit englischen Fehlertexten und ohne
    Endungsprüfung. (JSON-Handler für `HTTPException`; `SerialException` →
    503.)
11. **`/api/settings`** wartet blockierend auf die Maschinensperre und
    verlangt immer alle Felder. (`acquire(timeout=…)` + 409/503; Teil-Update.)
12. **`activity`** zeigt Firmware-Update, LightBurn und Web-Fahrten als
    `idle`. (`"firmware"`, `"lightburn"`, `"motion"` ergänzen.)
13. **`local_owner()`-Text** nennt immer LightBurn („– LightBurn zuerst
    trennen“), auch wenn `job` oder `firmware` die Steuerung hält.
14. **Kein HTTPS, keine Anmeldung** (bewusst).
15. **`lightburn_clients`** ist ein Zähler, kein „verbunden“-Flag.
16. **Rahmen**: Der Pi erzeugt keinen Rahmen aus einem gespeicherten Auftrag;
    die UI muss G-Code bauen. (`op=frame name=… mode=box` serverseitig.)
17. **Jog** prüft keine Arbeitsraumgrenzen selbst (nur Marlin-Softendstops).
    ⚠ Hardware
18. **Status direkt nach Dienststart** kann bei belegter Sperre ohne
    Transportfelder kommen (`stale_ms: null`).
