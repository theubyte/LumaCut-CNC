# Pi-API der nativen LumaCut Studio App

Dieses Dokument beschreibt jeden HTTP-Aufruf, den die native App
(`src/machine/`) an den Flask-Dienst des Pi 400 (`pi400/marlin/web.py`)
schickt. Alle Angaben stammen aus dem Code: `client.py` (HTTP),
`worker.py` (Poller, Befehls-Threads), `panel.py` (Oberfläche) und
`settings.py` (Einstellungen). Sie wurden gegen `pi400/marlin/web.py` und
`pi400/marlin/transport.py` geprüft (Stand: Commit mit `op=park`).

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
| `LONG_TIMEOUT_S` | 240 s | `op=home`, `op=probe`, `op=park` |
| `DEFAULT_TIMEOUT_S` | 60 s | alle anderen Aktionen, `GET /api/jobs…` |
| `UPLOAD_TIMEOUT_S` | 120 s | `POST /api/upload` |

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

- **Robustheit:** Kein Objekt → `ProtocolError`. Ohne `firmware` und ohne
  eines der Kernfelder `connected`, `homed`, `position`, `owner`,
  `emergency_latched` → `ProtocolError` „keine Statusfelder“. Fehlende oder
  falsch typisierte Einzelfelder fallen auf sichere Werte zurück (nicht
  gehomed, keine Position, Laser unbekannt). Bools werden auch aus `1`,
  `"true"`, `"ja"` usw. gelesen.
- **Wichtig:** `machine.status()` auf dem Pi nimmt `machine.lock`. Während
  Home, Park, Abtasten oder ein einzelner Jog-Befehl läuft, hält der Pi
  diese Sperre, und `/api/status` antwortet erst danach. Die App erkennt
  das als `StatusTimeout` und behandelt es tolerant (siehe unten).

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
  Jede Antwort des Pi, auch ein Fehler wie 503, ist endgültig und wird nicht
  wiederholt. M112 doppelt zu senden ist unkritisch. Klappt ein späterer
  Versuch, erhält die Meldung den Zusatz „(Versuch n)“. Nach dem letzten
  Fehlversuch kommt „NOT-AUS nicht bestätigt nach 3 Versuchen – physischen
  Not-Aus benutzen! (…)“.
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

- **Auslöser:** „Starten“ bzw. „Ein-Klick“ (beide mit Rückfrage), der
  Start-Knopf der Toolbar (`main.py`) und `send_gcode(start=True)`.
- **Payload:** `op=start name=<datei>` bzw. `op=autorun name=<datei>`
  (optional `x`, `y`; die App sendet keinen Punkt, der Pi nimmt die
  Motivmitte). **Zeitlimit:** 60 s (der Pi startet einen Hintergrund-Thread
  und antwortet sofort).
- **Antwort:** `message` „Job gestartet: …“ bzw. „Ein-Klick-Ablauf
  gestartet: Homing → Abtasten bei … → Fokus → … → Park“.
- **Fehler:** 400 „Vor dem Job referenzieren“ (nur `start`), „Unbekannte
  Auftragsdatei“, „X/Y-Tasterversatz zuerst unter Fokus & Taster
  eintragen“, „Motivmitte nicht bestimmbar …“, „Ein Auftrag läuft bereits“,
  „LightBurn hat inzwischen die Steuerung“, Belegt-/USB-Fehler.
- Fortschritt danach über `job.*` in `/api/status`.

### `POST /api/action op=abort`: Auftrag abbrechen

- **Auslöser:** Knopf „Abbrechen“ (nur bei aktivem Auftrag).
- **Payload:** `op=abort`. **Zeitlimit:** 60 s.
- **Antwort:** `message` „Abbruch angefordert: Laser aus, danach
  Parkposition“. **Fehler:** 400 „Kein laufender Auftrag“.

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

1. **Keine Schlüsselprüfung auf dem Pi:** `web.py` wertet `X-LumaCut-Key`
   nirgends aus. Jeder im Netz kann die API bedienen. Die App sendet den
   Schlüssel trotzdem und zeigt 401/403 als „Schlüssel abgelehnt“ an,
   sobald der Pi ihn prüft.
2. **Status blockiert während Bewegungen:** `/api/status` wartet auf
   `machine.lock`, das `safe_home`, `park_safezone`, `probe_workpiece` und
   jeder einzelne `command` halten. Während Home, Park und Abtasten gibt es
   deshalb keine Live-Position. Die App überbrückt das (Toleranz und
   Anzeige „Status alt“). Eine echte Lösung wäre ein Status-Snapshot ohne
   Sperre auf dem Pi.
3. **Keine eigene Fokus-Aktion:** „Fokus (G30)“ ist `op=probe`. Die
   Fokushöhe fährt der Pi erst beim nächsten Auftrag an.
4. **NOT-AUS ohne USB:** Der Pi setzt die Verriegelung und antwortet mit 503.
   M112 wurde dann **nicht** übertragen, und die App meldet das rot.
5. **Schlüssel im Klartext** in `QSettings`. Wer das nicht will, nutzt
   `LUMACUT_KEY`.
6. **Pi-Dienst aktualisieren:** `op=park` gibt es erst ab dem Commit
   „feat(pi400): op=park in /api/action“. Ältere Pis melden das klar (siehe
   oben).
7. **Kein HTTPS:** Die Verbindung läuft unverschlüsselt im LAN.
8. **CI:** Der GitHub-Workflow führt die nativen Tests (`pytest`) noch nicht
   aus. Lokal: `QT_QPA_PLATFORM=offscreen python -m pytest tests`.
