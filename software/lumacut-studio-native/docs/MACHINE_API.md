# Pi-API der nativen LumaCut Studio App

Dieses Dokument beschreibt jeden HTTP-Aufruf, den die native App
(`src/machine/`) an den Flask-Dienst des Pi 400 (`pi400/marlin/web.py`)
schickt. Alle Angaben stammen aus dem Code: `client.py` (HTTP),
`worker.py` (Poller, Befehls-Threads), `panel.py` (Oberfläche) und
`settings.py` (Einstellungen). Sie wurden gegen `pi400/marlin/web.py` und
`pi400/marlin/transport.py` geprüft (Stand: Commit mit `op=frame`).

Die vollständige, vom Client unabhängige Referenz aller Pi-Endpunkte und
`op`-Werte steht in [docs/PI_API_REFERENZ.md](../../../docs/PI_API_REFERENZ.md).

## Allgemeines

| Punkt | Wert |
| --- | --- |
| Basis-URL | Standard `http://lumacut.local:8080`. Eingabe `lumacut.local` oder eine IP genügt; `http://` und Port `8080` werden ergänzt (`normalize_base_url`). |
| Header | `Accept: application/json`; `X-LumaCut-Key: <Schlüssel>` bei **jeder** Anfrage, sofern ein Schlüssel gesetzt ist. Der Schlüssel wird nie geloggt (`repr()` von Client und Einstellungen zeigt `***`). |
| Aktionen | `POST /api/action`, `Content-Type: application/x-www-form-urlencoded`, Feld `op` + weitere Felder. Leere Felder (`None`) werden weggelassen. |
| Weiterleitungen | werden nicht verfolgt (3xx → `ProtocolError` „Pi leitet um … Adresse prüfen“). |
| HTTP-Bibliothek | nur stdlib (`urllib.request`); jede Anfrage ist eine eigene TCP-Verbindung. |
| Pi-Server | Flask, `threaded=True`: jede Anfrage läuft in einem eigenen Thread. Antworten tragen `Cache-Control: no-store`. |

### Antworten und Fehlerabbildung

Der Pi antwortet bei Erfolg mit JSON (`{"message": …}` bei Aktionen) und
bei Fehlern mit `{"error": "<Text>"}`. Fehlerhandler in `web.py`:

| Ausnahme auf dem Pi | HTTP |
| --- | --- |
| `ValueError`, `RuntimeError`, `PermissionError` | 400 |
| `TimeoutError`, `ConnectionError` | 503 |
| alles andere | 500 „Interner Fehler – Pi-Protokoll ansehen“ |
| Upload > 32 MB (`MAX_CONTENT_LENGTH`) | 413 (Werkzeug) |

So setzt der Client das um (`LumaCutClient._request`):

| Situation | Ausnahme in der App | Anzeige |
| --- | --- | --- |
| Zeitüberschreitung (Socket-Timeout) | `StatusTimeout` (Unterklasse von `ConnectionFailed`) „Pi antwortet nicht innerhalb N s (URL)“ | siehe Zustandsautomat |
| DNS, Verbindung abgelehnt/zurückgesetzt, Netz weg | `ConnectionFailed` „Pi nicht erreichbar (URL): Grund“ | Fehler |
| HTTP 401 / 403 | `AuthFailed` „Pi lehnt den Schlüssel ab (HTTP n): …“ | Badge „Schlüssel abgelehnt“ |
| HTTP 3xx | `ProtocolError` | Fehler |
| HTTP ≥ 400 sonst | `ApiError` „Pi lehnt ab (HTTP n): <error>“ (mit `status`) | „Letzte Meldung“ (rot) |
| Kein JSON-Objekt | `ProtocolError` „Ungültige Pi-Antwort (HTTP n)“ | Fehler |

Für den Grund wird `error`, ersatzweise `message` aus der Antwort benutzt.

### Zeitlimits

| Konstante (`client.py`) | Wert | Verwendet für |
| --- | --- | --- |
| `STATUS_TIMEOUT_S` | 4 s | `GET /api/status` |
| `ESTOP_TIMEOUT_S` | 3 s **pro Versuch** | `op=estop` |
| `ESTOP_RETRIES` / `ESTOP_RETRY_PAUSE_S` | 2 weitere Versuche / 0,2 s | `op=estop` |
| `ESTOP_DEADLINE_S` / `ESTOP_MIN_ATTEMPT_S` | 4 s für alle Versuche / min. 0,5 s je Versuch | `op=estop` |

Der Client nutzt **keinen System-Proxy** (`ProxyHandler({})`): Proxy-
Einstellungen aus der Umgebung oder der Windows-Registry würden Anfragen an
den Pi im LAN umleiten oder verzögern, auch den NOT-AUS.
| `LONG_TIMEOUT_S` | 240 s | `op=home`, `op=probe`, `op=park` |
| `DEFAULT_TIMEOUT_S` | 60 s | alle anderen Aktionen, `GET /api/jobs…` |
| `UPLOAD_TIMEOUT_S` + `UPLOAD_TIMEOUT_PER_MB_S` | 120 s + 10 s je angefangenes MB (`upload_timeout(size)`, bei 32 MB also 440 s) | `POST /api/upload` |

Der Pi hält Bewegungsanfragen offen, bis der SKR fertig ist. Deshalb sind
die Zeitlimits für Bewegungen lang.

## Aufrufe im Einzelnen

### `GET /api/status`: Statusabfrage

- **Auslöser:** Status-Poller (`StatusPoller`), standardmäßig jede Sekunde
  (`machine/poll_ms`, 250–10000 ms), sofort nach jedem Befehl (`poll_now`)
  und nach NOT-AUS. Außerdem `scanprobe.adapters` (Scan-Modul) über
  `client.status()`.
- **Payload:** keine.
- **Genutzte Antwortfelder** (`MachineStatus.from_json`):

  | Feld | Typ in der App | Anzeige / Verwendung |
  | --- | --- | --- |
  | `firmware` | muss `"marlin"` sein, falls vorhanden | sonst `ProtocolError` (z. B. alter GRBL-Dienst) |
  | `connected` | bool | „USB OK · state“ / „SKR nicht verbunden“ |
  | `state` | str | Marlin-Zustand neben „USB OK“ |
  | `owner` | str, Ersatzwert „Frei“ | „Frei“ / „Belegt: …“; `busy` |
  | `homed`, `z_homed`, `homing_verified` | bool | Homed-Anzeige; Jog/Park/Fokus nur wenn `homed` |
  | `position` | `[x, y, z]` oder `null` | Positionsanzeige |
  | `laser_armed` | bool oder **unbekannt** | „AKTIV“ / „Aus“ / „Unbekannt“ (fehlt das Feld, wird nie „Aus“ angezeigt) |
  | `laser_cooling_fan_on` | bool | „Aus · Lüfter nachlaufend“ |
  | `emergency_latched` | bool | „NOTSTOPP VERRIEGELT“; gibt „Notstopp quittieren“ frei und sperrt Bewegungen |
  | `fault` | str | „Letzte Meldung“ |
  | `lights`, `exhaust` | bool | nur geparst (keine Knöpfe) |
  | `workpiece_surface_z`, `laser_focus_z` | float oder `null` | Fokus-Anzeige, Scan-Modul |
  | `probe_xy_offset_mm` | gesetzt ja/nein | `probe_offset_set` |
  | `job.file`, `job.state`, `job.line`, `job.total`, `job.error` | | Auftragsanzeige mit Fortschritt; `homing`/`probing`/`running` = aktiv |
  | `frame.state`, `frame.mode`, `frame.line`, `frame.total`, `frame.error` | `FrameState` | Rahmenfahrt: `running` = aktiv (sperrt wie ein Auftrag), danach `complete`/`aborted`/`error`; fehlt bei älteren Pis → `idle` |
  | `activity` | str | `idle` / `job` / `framing` (nur geparst über `raw`; die App nutzt `frame.state` bzw. `owner == "frame"`) |
  | `busy` | bool → `pi_busy` | `true`: Der Pi fährt gerade (Sperre belegt), der Status ist ein Snapshot. Badge „ · Pi fährt“. Fehlt bei älteren Pis → `false` |
  | `stale_ms` | int oder `null` → `stale_ms` | Alter des gecachten Teils in ms (`0` = frisch). Fehlt bei älteren Pis → `0`, ungültig → `null` |

- **Robustheit:** Kein Objekt → `ProtocolError`. Ohne `firmware` und ohne
  eines der Kernfelder `connected`, `homed`, `position`, `owner`,
  `emergency_latched` → `ProtocolError` „keine Statusfelder“. Fehlende oder
  falsch typisierte Einzelfelder fallen auf sichere Werte zurück (nicht
  gehomed, keine Position, Laser unbekannt). Bools werden auch aus `1`,
  `"true"`, `"ja"` usw. gelesen.
- **Snapshot statt Blockieren (Pi ab „fix(pi400): /api/status blockiert
  nicht mehr hinter langen Fahrten“):** `machine.status()` braucht
  `machine.lock`, das Home, Park, Abtasten und jede Rahmenkante (`M400`)
  für die ganze Fahrt halten. `web.machine_snapshot()` wartet darauf
  höchstens 0,25 s (`STATUS_LOCK_WAIT_S`). Ist die Sperre belegt, kommt
  der letzte vollständige Status mit live gelesenen Feldern (`state`,
  `owner`, `homed`, `z_homed`, `emergency_latched`, `laser_armed`,
  `laser_cooling_fan_on`, `position`, `fault`, `workpiece_surface_z`,
  `connected`), dazu `busy: true` und `stale_ms`. Die Position ist dann
  die zuletzt von Marlin gemeldete, nicht die Live-Position während der
  Fahrt.
- **Ältere Pi-Dienste** ohne Snapshot halten `/api/status` bis zum Ende
  der Fahrt an. Die App erkennt das als `StatusTimeout` und behandelt es
  tolerant (siehe unten).

### `POST /api/action op=estop`: NOT-AUS (M112)

- **Auslöser:** Knopf „NOT-AUS (M112)“ im Panel, NOT-AUS in der Toolbar
  (`main.py`), Taste *Pause*.
- **Payload:** `op=estop`.
- **Pi:** setzt `stop_job`, ruft `machine.emergency_stop()` ohne
  `machine.lock` auf (schreibt M112 direkt) und antwortet sofort mit
  `{"message": "Marlin M112 ausgelöst – physischen Not-Aus prüfen"}`.
  Ist kein USB-Port offen, setzt der Pi die Verriegelung und antwortet mit
  **503** „Software-Notstopp NICHT übertragen: USB getrennt, physischen
  Not-Aus benutzen“.
- **Antwortfelder:** `message`.
- **Zeitlimit / Wiederholung:** 3 s pro Versuch, bis zu 3 Versuche mit
  0,2 s Pause, **nur** bei Netzfehlern (`ConnectionFailed`/`StatusTimeout`).
  Alle Versuche zusammen sind auf etwa 4 s begrenzt: Nach Ablauf startet
  kein neuer Versuch, ein späterer Versuch wird auf die Restzeit gekürzt
  (mindestens 0,5 s). Windows lehnt einen geschlossenen Port nicht sofort
  ab (≈ 2 s SYN-Wiederholungen); ohne die Grenze dauerte die Fehlermeldung
  dort 6–10 s.
  Jede Antwort des Pi, auch ein Fehler wie 503, ist endgültig und wird nicht
  wiederholt. M112 doppelt zu senden ist unkritisch. Klappt ein späterer
  Versuch, erhält die Meldung den Zusatz „(Versuch n)“. Nach dem letzten
  Fehlversuch kommt „NOT-AUS nicht bestätigt nach n Versuchen – physischen
  Not-Aus benutzen! (…)“ (n = 3, bei langsamer Ablehnung auch 2).
- **Ablauf in der App:** siehe Abschnitt „NOT-AUS-Verhalten“.

### `POST /api/action op=estop_reset`: Notstopp quittieren

- **Auslöser:** Knopf „Notstopp quittieren“, nur aktiv bei
  `emergency_latched`. Vorher fragt die App: „Ursache beseitigt und SKR neu
  gestartet (Reset-Taste oder 24 V/USB kurz getrennt)? Danach muss neu
  referenziert werden.“
- **Payload:** `op=estop_reset`. **Zeitlimit:** 60 s.
- **Pi:** `machine.clear_emergency()` gibt die Verriegelung nur frei, wenn
  der SKR wieder auf M115 antwortet. Bei Erfolg kommt `message` „Notstopp
  quittiert: SKR neu gestartet, bitte neu referenzieren“. Antwortet der SKR
  noch nicht, kommt 400 „SKR antwortet noch nicht: Reset-Taste …“.

### `POST /api/action op=home`: Referenzfahrt

- **Auslöser:** Knopf „Home“. **Payload:** `op=home`. **Zeitlimit:** 240 s.
- **Pi:** `local_owner()` und `machine.safe_home(owner="web", …)` (X/Y
  zuerst, dann Z). Hält `machine.lock` während der ganzen Fahrt.
- **Fehler:** 400 „Steuerung belegt durch … – LightBurn zuerst trennen“,
  400 „SKR beschäftigt: …“, 503 „Marlin SKR noch nicht per USB
  identifiziert“, außerdem Fehler aus `safe_home` (400/503).

### `POST /api/action op=jog`: Tippbetrieb

- **Auslöser:** Knöpfe X+/X−/Y+/Y−/Z+/Z− mit Schrittweite aus der Auswahl
  (0,1 / 1 / 10 mm). Nur aktiv, wenn gehomed.
- **Payload:** `op=jog`, `axis=X|Y|Z`, `distance=±0.1|±1.0|±10.0`.
  Die App prüft Achse und Schrittweite vorab (`ValueError`, ohne Anfrage).
- **Zeitlimit:** 60 s. **Antwort:** `message` „Bewegung ausgeführt: …“.
- **Fehler:** 400 „Marlin muss zuerst referenziert werden“, 400 „Ungültige
  Achse oder Schrittweite“, Belegt-/USB-Fehler aus `local_owner()`.
- Auch das Scan-Modul (`scanprobe.adapters.PiMachine`) nutzt `client.jog`.

### `POST /api/action op=probe`: Fokus (G30)

- **Auslöser:** Knopf „Fokus (G30)“ (`client.focus()` = `client.probe()`
  ohne Punkt) sowie das Scan-Modul (`PiProbe`, mit Punkt).
- **Payload:** `op=probe`, optional `x`, `y` (3 Nachkommastellen, nur
  gemeinsam). **Zeitlimit:** 240 s.
- **Pi:** fährt ggf. per G0 zum Punkt und tastet mit
  `machine.probe_workpiece` ab. Der Pi merkt sich die Oberfläche und fährt
  vor dem ersten Laserstrich eines Auftrags selbst auf Fokushöhe.
  **Antwort:** `message` „Werkstückoberfläche Z=… mm, Fokus Z=… mm“, `detail`
  (wird nicht genutzt).
- **Fehler:** 400 „Vor dem Abtasten referenzieren“, 400 „Abtastpunkt
  außerhalb X30..390 / Y30..370“, Belegt-/USB-Fehler.

### `POST /api/action op=park`: Parken

- **Auslöser:** Knopf „Park“ (nur gehomed). **Payload:** `op=park`.
  **Zeitlimit:** 240 s.
- **Pi (neu):** `local_owner()` und `machine.park_safezone(owner="web")`.
  Das ist dieselbe Routine wie LightBurn `M2` bzw. das Auftragsende: Laser
  aus, Z nur nach oben, dann X0/Y0. **Antwort:** `message` „Geparkt: Laser
  aus, Z-Rückzug, X0/Y0“.
- **Ältere Pi-Dienste** antworten mit 400 „Unbekannte Marlin-Aktion: park“.
  Die App zeigt dann „Pi-Dienst bietet noch kein Parken über die API
  (op=park fehlt in pi400/marlin/web.py)“. Abhilfe: Pi-Dienst aktualisieren.

### `POST /api/action op=frame`: Rahmen abfahren (Laser aus)

- **Auslöser:** Knopf „Rahmen“ im Panel (Auswahl „Rechteck“ = `box` /
  „Gummiband“ = `hull`, mit Rückfrage) sowie Toolbar „Rahmen“
  (*Strg+Umschalt+F*, Rechteck) und „Gummiband-Rahmen“ (*Alt+Umschalt+F*).
  Freigegeben nur verbunden, Status frisch, gehomed, kein Notstopp, kein
  Auftrag und keine Rahmenfahrt aktiv; die Toolbar-Aktionen folgen
  `frame_available_changed`.
- **Payload:** `op=frame gcode=<Rahmenprogramm> mode=box|hull`
  (form-encoded). Das Programm erzeugt `lumacut_job.estimate.frame_gcode`
  aus dem aktuellen Design, z. B.:

  ```
  ; LUMACUT FRAME (laser off)
  G21
  G90
  M5 I
  G0 X60.000 Y60.000
  G1 X120.000 Y60.000 F3000 S0
  …
  M5 I
  M400
  ```

  Die App prüft vorab Modus, leeres Programm und Größe (max. 64 KB).
  **Zeitlimit:** 60 s (der Pi startet einen Hintergrund-Thread und
  antwortet sofort).
- **Pi:** `local_owner()`, kein Notstopp, `homed`, dann `frame_program()`:
  pro Zeile nur `G0`/`G1` mit X/Y/F/S (S nur 0), `G21`, `G90`, `M5 I`,
  `M400`; kein `M3`, kein Z, keine Bögen, kein `G91`; Punkte in X0..390 /
  Y0..370, F 60..9000, max. 2000 Bewegungen; zusätzlich jede Zeile durch
  einen frischen `MarlinLaserGuard`. Danach `job_lock` (gemeinsam mit
  Aufträgen), Besitzer `frame`, Thread `_frame_worker`: `M5 I`, `G90`,
  jede Bewegung mit eigenem `M400`, vor jeder Zeile Abbruch-Check und
  `laser_enabled` muss aus sein, am Ende `M5 I`. **Kein Parken.**
  Die hochgeladene Datei, die Auftragsliste und `job.*` bleiben
  unverändert: Danach direkt „Starten“, ohne neu zu senden.
- **Antwort:** `{"message": "Rahmenfahrt gestartet (Rechteck|Gummiband, Laser
  aus)", "frame": {"state": "running", "mode": "box", "line": 0,
  "total": N, "error": ""}}`. Fortschritt über `frame.*` in `/api/status`;
  das Panel zeigt „Rahmenfahrt läuft (…) · Laser aus · <Auftrag> bleibt
  geladen“ und danach „Rahmenfahrt fertig / abgebrochen / fehlgeschlagen“.
- **Fehler (400):** „Vor dem Rahmen referenzieren“, „Rahmen Zeile n: …“
  (z. B. „Laserleistung im Rahmen verboten (nur S0)“), „Rahmenart muss box
  oder hull sein“, „Ein Auftrag oder Rahmen läuft bereits“, „Steuerung
  belegt durch job …“, „Notstopp aktiv – erst quittieren“; 503 ohne USB.
  Während einer Rahmenfahrt lehnen andere Befehle mit „Rahmenfahrt läuft –
  abwarten oder abbrechen“ ab.
- **Abbrechen:** `op=abort` stoppt an der nächsten Ecke („Rahmen-Abbruch
  angefordert …“), `op=estop` sofort. „Abbrechen“ bleibt auch bei altem
  Status nutzbar, weil der Pi `machine.lock` während jeder Kante hält.
- **Ältere Pi-Dienste** antworten mit 400 „Unbekannte Marlin-Aktion:
  frame“. Die App zeigt „Pi-Dienst bietet noch keine Rahmenfahrt über die
  API (op=frame fehlt …)“.

### `POST /api/upload`: Auftrag senden

- **Auslöser:** Knopf „Senden“ (gewählte Datei) und
  `MachinePanel.send_gcode()` (Export aus dem Canvas, optional direkt danach
  `op=start`).
- **Payload:** `multipart/form-data`, Feld `file`, Dateiname = Auftragsname
  (nur Basisname, Endung `.gcode`/`.gc`/`.nc`, max. 32 MB, UTF-8). Die App
  prüft Name und Größe vorab.
- **Zeitlimit:** 120 s. **Antwort:** `message` „Marlin-Auftrag geprüft und
  gespeichert: …“.
- **Fehler:** 400 bei falschem Namen, falscher Endung oder Preflight-Fehler
  (unzulässiger G-Code, Sicherheitszone), 413 bei > 32 MB.

### `POST /api/action op=start` / `op=autorun`: Auftrag starten

- **Auslöser:** Für Entwürfe der große **„Start“** der Hauptansicht
  (`one_click.start`, Scan Probe). Im Panel heißt der Knopf
  **„Datei-Auftrag starten“** (`autorun` für die gewählte/gesendete Datei,
  mit Rückfrage; sendet eine noch nicht gesendete Datei im selben Klick
  vorher). Dazu `send_gcode(autorun=True)` (folgt dem gewählten Ursprung)
  und `MachinePanel.autorun_task(name)` (Platzierung + `op=autorun` für
  den Ein-Klick-Controller). `op=start` nur noch über „Ohne Automatik
  starten“ in der eingeklappten Gruppe **„Erweitert: Bewegung, Taster,
  Jog“** (dort auch Home, Park, Fokus/G30, Jog, Notstopp quittieren), den
  Knopf „Hochgeladenen Auftrag starten“ unter „Mehr“ (`main.py`) und
  `send_gcode(start=True)`.
- **Payload:** `op=start name=<datei>` bzw. `op=autorun name=<datei>`
  (optional `x`, `y` = ein einzelner Abtastpunkt; die App sendet keinen,
  der Pi plant das Raster bzw. nimmt auf altem Pi die Motivmitte;
  `placement=1` nach `op=place`). **Zeitlimit:** 60 s (der Pi startet einen Hintergrund-Thread
  und antwortet sofort).
- **Antwort:** `message` „Job gestartet: …“ bzw. „Ein-Klick-Ablauf
  gestartet: Homing → Abtasten bei … → Fokus → … → Park“.
- **Fehler:** 400 „Vor dem Job referenzieren“ (nur `start`), „Unbekannte
  Auftragsdatei“, „X/Y-Tasterversatz zuerst unter Fokus & Taster
  eintragen“, „Motivmitte nicht bestimmbar …“, „Ein Auftrag läuft bereits“,
  „LightBurn hat inzwischen die Steuerung“, Belegt-/USB-Fehler.
- Fortschritt danach über `job.*` in `/api/status`. Der echte Pi
  (`web.py _execute_job`) sendet `job = {file, state, line, total, error,
  probe}`, **kein** `job.phase`: `state` `homing` (nur wenn nicht
  referenziert) → `probing` (`job.probe = {"done", "total"}`, total =
  Punkte + 1) → `running` → `complete`, sonst `aborted`/`error` mit
  `job.error`. Fokus ist Teil von Abtasten/Laufen; nach der letzten Zeile
  leert der Pi den Puffer und parkt, noch mit `state=running` und
  `line == total`. Studio leitet daraus die Phase `finishing` ab und das
  Panel zeigt **„Letzte Bahnen, dann Parken“** (`JobState.phase`): Die
  gepufferten Bahnen können noch brennen, Studio behauptet nie „Laser
  aus“, bevor `complete` kommt. „Abtasten 3 / 13“ samt Balken während
  `probing`. Ein künftiges explizites `job.phase` (`focusing`, `parking`)
  hat Vorrang. `JobState.active` zählt
  `homing/probing/focusing/running/finishing/parking`. Hinweis: Der Pi
  setzt beim Autorun zuerst kurz `running` mit `line = 0`, dann erst
  `homing`/`probing` (Wunsch an Claude, ZUSAMMENARBEIT §6).
  Abbrechen und NOT-AUS sind in jeder Phase bedienbar.
- **Merkmal `autorun_mesh`** (`/api/status` `features`, `MachineStatus.features`,
  `has_feature`): Der Pi tastet ein Raster über dem Motiv ab und
  korrigiert die Höhe. Fehlt es (älterer Pi), tastet `autorun` nur einen
  Punkt in der Motivmitte; Panel-Tooltip und Rückfrage nennen das
  (`OLD_PI_MESH`, „Pi aktualisieren“).
- **Älterer Pi ohne `op=autorun`:** Der Client ersetzt „Unbekannte
  Marlin-Aktion: autorun“ durch `client.OLD_PI_AUTORUN` („Pi-Dienst
  aktualisieren … oder unter „Erweitert“ ohne Automatik starten“).

### Auftrags-Ursprung: `op=origin_set` / `origin_clear` / `place` / `place_clear`

Neuer Pi-Dienst (ab „feat(pi400): Auftrags-Ursprung …“). Ein Auftrag läuft
**absolut** (wie gezeichnet), solange in „Auftrag“ der Ursprung „Absolut“
gewählt ist. Das ist der Standard und genau das bisherige Verhalten.

- **Ursprung** (Auswahl im Panel):
  - `absolute`: wie gezeichnet.
  - `current`: Bezugspunkt auf die aktuelle Kopfposition.
  - `user`: Bezugspunkt auf den auf dem Pi gespeicherten Benutzer-Ursprung.
- **Bezugspunkt** (`anchor`): `tl`/`tr`/`bl`/`br`/`center` der
  **Laserbahnen** (nicht der Leerfahrten), benannt nach der **sichtbaren
  Ecke von vorne**: X0/Y0 (Endschalter) liegt oben rechts, X wächst nach
  links, Y nach vorne. `tr` (Standard) = kleinstes X/kleinstes Y.
  - Ein Pi ab 2026-10-26 meldet `coord_convention` = `origin_top_right`.
    Fehlt das Feld (älterer Pi, dort hieß „l“ kleines X), tauscht
    `client.wire_anchor()` links/rechts. Die gewählte sichtbare Ecke stimmt
    also mit beiden Pi-Ständen; die Liste zeigt die Namen zurückübersetzt.
- **Joggen** (`machine/panel.py`): Kreuz wie von vorne gesehen:
  „← X +“ links, „X − →“ rechts, „↑ Y −“ oben (Schalterseite),
  „↓ Y +“ unten (Tür). Die Positionsanzeige zeigt Maschinen-mm (Tooltip
  erklärt Nullpunkt und Richtungen).
- `op=origin_set` (optional `x`, `y` in Maschinen-mm, sonst Kopf-XY per
  M114): Knopf „Ursprung = Kopf“ bzw. `MachinePanel.set_user_origin(x, y)`
  (Haken für den Kamera-Scan). Braucht Referenzfahrt; der Punkt muss in
  X30..390 / Y30..370 liegen. Wird in `/var/lib/lumacut/marlin.json`
  gespeichert. `op=origin_clear` löscht ihn.
- `op=place name=… origin=… anchor=…`: Der Pi verschiebt den gespeicherten
  Auftrag (nichts fährt) und prüft auf den **verschobenen** Zeilen:
  - Referenzfahrt;
  - alle Fahrten in 0..Verfahrweg;
  - alle Laserbahnen in 30..Verfahrweg (Safezone);
  - Laser-Guard/Preflight;
  - keine relativen X/Y-Bewegungen (`G91` mit X/Y ist nicht platzierbar).

  Antwort: `message`, `placement` (`file`, `origin`, `anchor`, `dx`, `dy`,
  `target`, `bounds`, `travel`). Fehler 400 mit Klartext, z. B.
  „Platziertes Motiv … außerhalb des Schneidbereichs …“.
- `op=start` / `op=autorun` / `op=frame` mit `placement=1` (bei `frame`
  zusätzlich `name`) nutzen genau diese Platzierung. Der Rahmen fährt also
  dieselbe Verschiebung wie der Auftrag, auch wenn er den Kopf bewegt hat.
- **Verfall einer Platzierung:**
  - neuer Upload oder Löschen der Datei (Prüfsumme);
  - bei `current` zusätzlich `home`, `jog`, `moveto`;
  - bei `user` ein neuer Benutzer-Ursprung.

  Dann antwortet der Pi „… neu platzieren“, und die App platziert einmal
  neu.
- Ohne `placement`/`origin` laufen `start`/`autorun` unverändert absolut
  (LightBurn, Pi-Web-UI, ältere Studio-Versionen).
- **Status:** `origin` = `{modes, anchors, user, placement}`. Fehlt der
  Schlüssel, ist der Pi zu alt: Die App sperrt die Auswahl, zeigt „Pi-Dienst
  zu alt: nur absolute Aufträge – Pi aktualisieren“ und schickt **nie**
  Ursprungsfelder (ein alter Pi würde sie ignorieren und absolut lasern).
  Direkte Client-Aufrufe melden „Pi-Dienst kennt noch keine
  Ursprungs-Optionen (op=… fehlt … – Pi aktualisieren)“.
- Rahmen mit Ursprung braucht einen gesendeten Auftrag (die Verschiebung
  hängt an ihm).
- ⚠ Hardware: Position nach dem Verschieben am echten Gerät nicht geprüft.

### Auftrags-Warteschlange: `op=queue_add` / `queue_run` / `queue_pause` / `queue_skip` / `queue_remove` / `queue_clear`

- **Auslöser:** Gruppe „Warteschlange“ im Maschinen-Panel: „Einreihen“
  (gesendeter Auftrag mit dem gewählten Ursprung), „Abarbeiten“ (mit
  Bestätigung), „Anhalten“ (nach dem laufenden Auftrag), „Überspringen“ /
  „Entfernen“ (gewählter Eintrag), „Leeren“. Client: `queue_add(name,
  origin, anchor, placement=False)`, `queue_run()`, `queue_pause()`,
  `queue_skip(id)`, `queue_remove(id)`, `queue_clear()`.
- **Payload:** `queue_add`: `name`, `origin`, `anchor` (oder
  `placement=1` = die Platzierung aus `op=place`); `queue_skip`/`queue_remove`:
  `id`. **Antwort:** `message`, `queue`.
- Der Pi friert beim Einreihen Versatz (`dx`/`dy`) und Prüfsumme ein: Ein
  späteres Tippen verschiebt eingereihte Aufträge nicht, eine geänderte
  Datei wird beim Abarbeiten abgelehnt („neu einreihen“).
- Abarbeiten: ein Auftrag nach dem anderen, je wie `op=start` (Parken
  danach) – **ohne** Abtasten und ohne Fokuskorrektur, und nur referenziert
  („Vor der Warteschlange referenzieren“). Panel-Tooltip und Rückfrage von
  „Warteschlange starten“ sagen das (`panel.QUEUE_NOTE`). Relative
  Fokus-Absenkungen (`G91`/`G0 Z-…`) gehen dabei roh an Marlin. Fehler, Abbrechen oder NOT-AUS stoppen die Warteschlange; der
  Rest bleibt „wartet“. Während sie läuft, sind Start/Home/Rahmen/Tippen
  gesperrt, „Abbrechen“ bleibt aktiv (auch zwischen zwei Aufträgen).
- **Status:** `queue` = `{items: [{id, file, origin, anchor, dx, dy,
  target, bounds, state, error}], state, current, max}`. Fehlt der
  Schlüssel, ist der Pi zu alt: Die Gruppe ist gesperrt mit „Pi-Dienst zu
  alt: keine Warteschlange – Pi aktualisieren“; Client-Aufrufe melden
  „Pi-Dienst kennt noch keine Auftrags-Warteschlange (op=… fehlt … – Pi
  aktualisieren)“.
- Nicht persistent: Ein Neustart des Pi-Dienstes leert die Liste.
- ⚠ Hardware: am echten Gerät nicht nachgewiesen.

### `POST /api/action op=abort`: Auftrag abbrechen

- **Auslöser:** Knopf „Abbrechen“ (nur bei aktivem Auftrag oder Rahmenfahrt).
- **Payload:** `op=abort`. **Zeitlimit:** 60 s.
- **Antwort:** `message` „Abbruch angefordert: Laser aus, danach
  Parkposition“ bzw. bei Rahmenfahrt „Rahmen-Abbruch angefordert: stoppt an
  der nächsten Ecke, Laser bleibt aus“. **Fehler:** 400 „Kein laufender
  Auftrag“.

### Im Client vorhanden, aber ohne Knopf

| Methode | Anfrage | Hinweis |
| --- | --- | --- |
| `connect_machine()` | `op=connect` | SKR neu identifizieren (M115); 503 wenn nicht erreichbar |
| `jobs()` | `GET /api/jobs` → `files[]` (`name`, `bytes`) | gespeicherte Aufträge |
| `job_geometry(name)` | `GET /api/jobs/<name>/geometry` → `bounds`, `center`, `probe_candidates`, … | Vorschau; 400 „Auftrag nicht gefunden“ |

Nicht genutzt werden `op=info|position|endstops|light|exhaust`,
`/api/settings`, `/api/commission` und `/api/firmware`.

## Zustandsautomat der Verbindung

Zustände (`worker.ConnState`): `disconnected` („Nicht verbunden“),
`connecting` („Verbinde …“), `connected` („Verbunden“), `error` („Fehler“),
`auth_failed` („Schlüssel abgelehnt“).

```
disconnected --Verbinden--> connecting --Status OK--> connected
connecting/connected --401/403--> auth_failed
connecting/connected --kaputte Antwort (ProtocolError)--> error
connected --Netzfehler 2× in Folge (FAILURE_TOLERANCE)--> error
connecting --Netzfehler--> error
connected --Timeout, Befehl läuft ODER letzter OK < 20 s--> connected (Daten veralten)
connected --Timeout, sonst (TIMEOUT_GRACE_S = 20 s)--> error
error/auth_failed --Status OK--> connected
beliebig --Trennen / Beenden--> disconnected
```

- Der Poller läuft in einem eigenen Daemon-Thread und blockiert die
  Oberfläche nie. Signale gehen per Queued Connection in den GUI-Thread.
  Signale eines alten Pollers werden verworfen (`sender()`-Prüfung).
- **Fremdbelegung:** `owner` „Frei“, leer und `monitor` (Heartbeat) gelten
  als frei (`client.TRANSIENT_OWNERS`). Jeder andere Besitzer außer `job`
  und `frame` (z. B. `lightburn`, `web`, `firmware`) ist
  `MachineStatus.foreign_owner` und sperrt Home, Park, Fokus, Start,
  Ein-Klick, Rahmen und Jog. NOT-AUS bleibt bedienbar.
- **Senden/Start:** Vor jedem Upload vergisst das Panel den zuletzt
  gesendeten Auftrag (`_uploaded`). Er wird erst nach erfolgreichem
  Upload neu gesetzt (mit Generationszähler). Ein fehlgeschlagener oder
  überholter Upload kann also nie einen alten Auftrag starten.
- **Backoff:** nach Fehlern Intervall × (1 + Fehlerzahl), höchstens 5 s.
  Nach einem Erfolg gilt wieder das normale Intervall.
- **Veraltete Daten:** Ist der letzte gute Status älter als 3 s
  (`panel.STALE_AFTER_S`), zeigt das Badge gelb „Pi beschäftigt (<Befehl>)
  · Status N s alt“ bzw. „Keine Statusdaten“, und die Positionsanzeige wird
  grau. **Alle Bedienknöpfe außer NOT-AUS werden gesperrt**, bis wieder
  frische Daten kommen.
- **Befehle** laufen in eigenen Daemon-Threads (`CommandRunner`), immer nur
  einer gleichzeitig („Es läuft noch ein Befehl“). Während ein Befehl läuft,
  teilt das Panel das dem Poller mit (`set_command_running`), damit
  Zeitüberschreitungen durch die Pi-Sperre nicht als Fehler gelten.
- **Fremde Vorgänge** (z. B. Scan-Modul): `MachinePanel.client` liefert
  den Client, `set_external_operation("Scan")` meldet einen laufenden
  Vorgang an (Poller toleriert Timeouts, Badge nennt ihn, Bedienknöpfe
  gesperrt), `set_external_operation(None)` beendet ihn.
- **Fenster schließen:** `MachinePanel.confirm_close()` fragt nach,
  solange Auftrag, Rahmenfahrt, ein Befehl oder ein fremder Vorgang läuft
  („Schließen stoppt die Maschine NICHT“). Bei „Nein“ bleibt das Fenster
  offen (`main.py` `closeEvent`).
- **Trennen** stoppt den Poller nach höchstens 200 ms (danach kein Signal
  mehr). **Beenden** wartet höchstens 1 s auf laufende Anfragen (z. B. die
  Antwort eines NOT-AUS) und hängt nie an einem langen Home.

## NOT-AUS-Verhalten

1. Der NOT-AUS-Knopf ist **nie** gesperrt: nicht durch einen laufenden
   Befehl, nicht durch veraltete Daten, nicht durch Fehlerzustände und auch
   nicht ohne Verbindung.
2. Er läuft **an der Befehlswarteschlange vorbei** in einem eigenen Thread
   mit eigener HTTP-Verbindung (`run_urgent`). Bis zu 3 NOT-AUS-Anfragen
   dürfen gleichzeitig laufen; darüber zeigt die App „NOT-AUS wird bereits
   gesendet …“.
3. Ohne Verbindung baut die App aus Adresse und Schlüssel in den Feldern
   einen Client. Ist die Adresse ungültig, erscheint „NOT-AUS nicht
   gesendet: … – physischen Not-Aus benutzen!“.
4. Rückmeldung unter dem Knopf, mit Uhrzeit:
   - „NOT-AUS gesendet – warte auf Bestätigung …“ (gelb)
   - „NOT-AUS bestätigt: <Pi-Meldung>“ (grün)
   - „NOT-AUS NICHT bestätigt: <Grund> – physischen Not-Aus benutzen!“ (rot)
5. Danach fragt der Poller sofort den Status ab. `emergency_latched`
   erscheint als „NOTSTOPP VERRIEGELT“, und alle Bewegungen bleiben bis zur
   Quittierung gesperrt.
6. Quittieren: Ursache beseitigen, SKR per Reset-Taste oder kurz 24 V/USB
   neu starten, „Notstopp quittieren“ bestätigen, dann neu referenzieren
   (Home).

Der Software-NOT-AUS ersetzt **nicht** den physischen Not-Aus-Schalter.

## Einstellungen und Umgebungsvariablen

| Einstellung (`QSettings`, Org „LumaCut“, App „LumaCut Studio“) | Bedeutung | Standard |
| --- | --- | --- |
| `machine/base_url` | Pi-Adresse | `http://lumacut.local:8080` |
| `machine/api_key` | Wert für `X-LumaCut-Key` | leer |
| `machine/poll_ms` | Status-Intervall (250–10000) | 1000 |
| `machine/auto_connect` | beim Start verbinden | aus |

- Windows: `HKCU\Software\LumaCut\LumaCut Studio`.
- **`LUMACUT_KEY`**: Hat Vorrang vor dem gespeicherten Schlüssel und wird
  nicht gespeichert. Gedacht für gemeinsam genutzte PCs.
- Gespeichert wird beim Klick auf „Verbinden“.

## Bekannte Lücken (geprüft gegen den Pi-Code)

1. **Keine Schlüsselprüfung auf dem Pi (bewusst):** `web.py` wertet
   `X-LumaCut-Key` nirgends aus. Die Pi-Weboberfläche ist absichtlich ohne
   Anmeldung (Commit 78ce258, Test in `tests/test_marlin_gateway.py`).
   Jeder im LAN kann die API bedienen. Die App sendet den Schlüssel
   trotzdem und zeigt 401/403 als „Schlüssel abgelehnt“ an, falls der Pi
   ihn einmal prüft.
2. **Status während Bewegungen: gelöst** durch den Snapshot (`busy`,
   `stale_ms`, siehe `GET /api/status`). Nur ältere Pi-Dienste blockieren
   noch; dafür bleibt die Toleranz („Status alt“) in der App.
3. **Keine eigene Fokus-Aktion:** „Fokus (G30)“ ist `op=probe`. Die
   Fokushöhe fährt der Pi erst beim nächsten Auftrag an.
4. **NOT-AUS ohne USB:** Der Pi setzt die Verriegelung und antwortet mit 503.
   M112 wurde dann **nicht** übertragen, und die App meldet das rot.
5. **Schlüssel im Klartext** in `QSettings`. Wer das nicht will, nutzt
   `LUMACUT_KEY`.
6. **Pi-Dienst aktualisieren:** `op=park` gibt es erst ab dem Commit
   „feat(pi400): op=park in /api/action“. Ältere Pis melden das klar (siehe
   oben).
7. **Rahmenfahrt:** `op=frame` gibt es erst ab „feat(pi400): op=frame …“.
   Während jeder Kante hält der Pi `machine.lock` (wegen `M400`). Ein
   aktueller Pi liefert dann den Snapshot (`busy: true`), ein älterer lässt
   den Status kurz „alt“ werden; Abbrechen und NOT-AUS bleiben bedienbar. Abbrechen wirkt an der nächsten Ecke, nicht mitten
   in der Kante. Die Pi-Weboberfläche hat keinen eigenen Rahmen-Knopf.
8. **Kein HTTPS:** Die Verbindung läuft unverschlüsselt im LAN.
9. **Tests:** Die Maschinen-Tests (`tests/test_machine_*.py`) laufen gegen
   den Fake-Pi (`tests/fake_pi.py`) und im Workflow
   `lumacut-studio-native.yml` headless vor dem .exe-Build. Gegen einen
   echten Pi ist die Anbindung noch nicht getestet. Lokal:
   `QT_QPA_PLATFORM=offscreen python -m pytest tests`. Die Tests prüfen
   keine knappen Zeitgrenzen: Netzfehler werden deterministisch simuliert,
   es wird auf Bedingungen gewartet (bis 15 s), und Zeitvergleiche haben
   großen Abstand zur simulierten Verzögerung, damit sie auch auf
   langsamen Windows-Runnern stabil sind.
10. **Pi-Seite im Überblick:** Was der Pi-Dienst kann, wie man ihn
    aktualisiert und was offen ist: [PI_STATUS_UND_OFFENE_PUNKTE.md](../../../docs/PI_STATUS_UND_OFFENE_PUNKTE.md).
11. **Ursprung nicht im Dokument:** Ursprung und Bezugspunkt sind eine
    Einstellung im Maschinen-Panel, nicht Teil des Canvas-Dokuments oder
    Exports. Den Kamera-Scan bindet `MachinePanel.set_user_origin(x, y)` /
    `set_job_origin(origin, anchor)` an (noch nicht verdrahtet).
12. **Warteschlange:** nur im Speicher des Pi (max. 50 Einträge), keine
    Reihenfolge ändern (entfernen und neu einreihen), keine Ansicht in der
    Pi-Web-UI.
