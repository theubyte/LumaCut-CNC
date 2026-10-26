# Pi 400: Stand des Pi-Dienstes und offene Punkte (für LumaCut Studio)

Stand: 26.10.2026, geprüft gegen `pi400/` auf `main`. Alle Aussagen stammen
aus dem Code (`pi400/marlin/web.py`, `transport.py`, `firmware_flash.py`,
`install.sh`, `update.sh`, `recover.sh`) und den Tests. **Markierung
„⚠ Hardware“** heißt: nur mit Fake-SKR bzw. Fake-Pi in den Tests geprüft,
an der echten Maschine nicht nachgewiesen.

Bedienung, Installation und API-Kurzreferenz stehen in
[PI_BETRIEB.md](PI_BETRIEB.md). Die Studio-Seite steht in
[MACHINE_API.md](../software/lumacut-studio-native/docs/MACHINE_API.md).

## 1. Was der Pi-Dienst heute kann

Dienst `lumacut-marlin.service` (`python3 -m marlin.web`, Benutzer
`lumacut`, Programm in `/opt/lumacut`). Er spricht per USB mit dem SKR
(Marlin) und bietet:

- **HTTP 8080:** Web-UI (`/`) und API für Studio und Tablet.
- **TCP 23:** Marlin-Gerät für LightBurn (Übergangsphase).

### Endpunkte (`web.py`)

| Methode | Pfad | Kurz |
|---|---|---|
| GET | `/` | Web-UI (`index.html`), **ohne Anmeldung** |
| GET | `/api/status` | Maschinenzustand, Auftrag (`job`), Rahmen (`frame`), `activity`, `busy`, `stale_ms`, `camera`, `firmware_update`, `config` |
| POST | `/api/action` | `op=` siehe unten |
| POST | `/api/upload` | G-Code-Auftrag (`file`), mit Preflight |
| GET | `/api/camera/snapshot?w=&h=` | ein JPEG der Kopfkamera (`LUMACUT_CAMERA`, Standard `/dev/video0`, per `ffmpeg`), fährt nie; ohne Kamera 503 |
| GET/PUT | `/api/camera/calibration` | Kamera-Kalibrierung (Datei `/etc/lumacut/camera_calibration.json`, Rückfall `/var/lib/lumacut`), PUT mit `revision`, 409 bei Konflikt |
| GET | `/api/jobs` | gespeicherte Aufträge |
| GET | `/api/jobs/<name>/content` | Roh-G-Code (Vorschau) |
| POST | `/api/jobs/<name>/delete` | Auftrag löschen (nicht den laufenden) |
| GET | `/api/jobs/<name>/geometry` | Motivgrenzen, Mitte, Abtastkandidaten |
| POST | `/api/settings` | Z-Rückzug, Fokusabstand, Schalter→Spitze, X/Y-Tasterversatz |
| POST | `/api/commission` | Mechanik-Freigabe (`confirm=TESTS_BESTANDEN_LASER_GETRENNT`, `enable=0/1`) |
| POST | `/api/firmware` | SKR-Firmware flashen (`file`) |

Fehler: `ValueError`/`RuntimeError`/`PermissionError` → 400,
`TimeoutError`/`ConnectionError` → 503, jeweils `{"error": "…"}`.
Sonstiges → 500 „Interner Fehler – Pi-Protokoll ansehen“.

### Aktionen `POST /api/action op=…`

| `op` | Wirkung | Voraussetzung |
|---|---|---|
| `estop` | `stop_job` setzen, M112 **ohne** Sperre senden, Verriegelung | keine |
| `estop_reset` | Verriegelung lösen, wenn das SKR nach Reset wieder M115 beantwortet | kein Besitzer |
| `connect` | SKR identifizieren (M115 + LumaCut-Kennung) | – |
| `home` | atomare Referenzfahrt: X/Y, dann Z, Rückzug (dieselbe Routine wie LightBurn `G28`) | frei, Idle |
| `info` / `position` / `endstops` | M115 / M114 / M119 | frei, Idle |
| `jog` | `axis` X/Y/Z, `distance` ±0,1/1/10 mm, mit `M400` | gehomed, frei |
| `light` / `exhaust` | M7/M8/M9 | frei |
| `probe` | G30 an aktueller oder angegebener XY (X30..390/Y30..370) | gehomed, frei |
| `park` | Laser aus, Z nie abwärts, X0/Y0 (`park_safezone`) | gehomed, frei |
| `moveto` | `x`/`y` absolut (X0..390/Y0..370), Laser aus, Z wird nur angehoben (Kamera-Scan) | gehomed, frei, Laser aus |
| `frame` | Rahmenfahrt mit Laser aus (`gcode`, `mode=box\|hull`) | gehomed, frei, kein Notstopp |
| `origin_set` | Benutzer-Ursprung speichern (`x`/`y` oder Kopf-XY), muss in X30..390/Y30..370 liegen | gehomed, frei |
| `origin_clear` | Benutzer-Ursprung löschen | frei |
| `place` | Auftrag `name` auf `origin` (`absolute`/`current`/`user`) mit `anchor` verschieben und prüfen, nichts fährt | gehomed (außer `absolute`), frei |
| `place_clear` | Platzierung verwerfen | frei |
| `start` | Auftrag `name` abarbeiten, danach Parken; mit `placement=1` (oder `origin`/`anchor`) platziert | gehomed, frei |
| `autorun` | Ein-Klick: Homing → Abtasten unter Motivmitte (oder `x`/`y`) → Fokus → Auftrag → Parken | Tasterversatz gesetzt |
| `abort` | Rahmen: Stopp an der nächsten Ecke. Auftrag: Laser aus, Parken | läuft etwas |

Unbekannte `op` → 400 „Unbekannte Marlin-Aktion: <op>“.

### Sicherheit

- **Ein Besitzer zur Zeit** (`machine.owner`): `None` (Status „Frei“),
  `web` (während der Referenzfahrt), `job`, `frame`, `lightburn`,
  `firmware`. Einzelne Befehle (`command()`, auch Heartbeat `monitor` und
  `shutdown`) setzen keinen Besitzer, halten aber `machine.lock`.
  `local_owner()` lehnt Web/Studio-Befehle ab, solange jemand anderes
  besitzt („Steuerung belegt durch … – LightBurn zuerst trennen“ bzw.
  „Rahmenfahrt läuft – abwarten oder abbrechen“).
- **LightBurn:** `serve_client` übernimmt nur, wenn kein Besitzer da ist und
  das SKR identifiziert ist. Sonst schließt es die Verbindung kommentarlos.
- **Laser-Guard** (`MarlinLaserGuard`): prüft jede Zeile beim Upload
  (Preflight) und beim Senden. Nur `M3 I`, kein `M4`, kein GRBL.
- **30-mm-Safezone:** Motive mit Laserleistung müssen in X30..390 / Y30..370
  liegen. Das prüft der Preflight vor dem Start.
- **Mechanik-Freigabe:** Upload, Rahmen und Aufträge verlangen
  `homing_verified` (`/api/commission`). Das ist ausdrücklich **keine**
  elektrische Prüfung (`hardware_electrically_verified=False`).
- **Notstopp:** M112 geht ohne `machine.lock` raus, wirkt also auch während
  langer Fahrten. Danach muss das SKR zurückgesetzt werden, bevor
  `estop_reset` freigibt. Abbruchfehler eskalieren auf M112.
- **Lüfternachlauf:** 180 s über `service_cooldown` im Monitor-Thread. Das
  hängt am Pi und ist nicht absturzsicher.
- **Update-Sperre:** `update.sh` aktualisiert nur bei `owner == "Frei"` und
  Zustand Idle/Disconnected/Unknown/Alarm und flasht nie das SKR.

### Upload und Preflight

- Nur `.gcode`/`.gc`/`.nc`, nur Basisname, höchstens 32 MB
  (`MAX_CONTENT_LENGTH`), UTF-8.
- Jede Zeile durchläuft den Laser-Guard. `G28`/`G30`/`M2` laufen als
  Pi-Routinen.
- Das Motiv muss in der Safezone liegen. Nach dem Preflight wird atomar
  gespeichert (`.partial` → `replace`).
- `start` prüft den Auftrag beim Start erneut.

### Abtasten und Fokus

- `op=probe` und `G30` tasten über den X/Y-Tasterversatz ab. Maschinen-Z0
  bleibt unverändert.
- Fokushöhe = Oberfläche + `focus_gap_mm`. Der Pi fährt sie vor dem ersten
  Laserstrich selbst an.
- `/api/status` liefert `estimated_tip_gap_mm` und
  `estimated_focus_adjust_mm`. Das sind Schätzwerte, keine Messung.

### Rahmen (`op=frame`)

- Nimmt nur `G0`/`G1` mit X/Y (`S0`), `G21`, `G90`, `M5`, `M5 I`, `M400`
  an. Kein `M3`, kein Z, keine Bögen, `F` 60..9000, alle Punkte im
  Verfahrbereich.
- Höchstens 64 KB und 2000 Fahrbewegungen. Jede Zeile läuft zusätzlich
  durch einen frischen Laser-Guard.
- Nutzt `job_lock`/`stop_job` gemeinsam mit Aufträgen, also nie beide
  gleichzeitig. Der hochgeladene Auftrag und sein Status bleiben
  unverändert.
- Nach jeder Kante kommt `M400`, damit `abort` an der nächsten Ecke wirkt.
  Ist der Laser unerwartet aktiv, stoppt der Rahmen.
- Es wird nicht geparkt.
- ⚠ Hardware.

### Auftrags-Ursprung (`op=place`, `origin_set`)

- Reine Rechnung in `pi400/marlin/placement.py`: verschiebt X/Y absoluter
  `G0`–`G3`; Bögen (I/J relativ) bleiben gültig. Grenzen inkl.
  Bogenextreme.
- Geprüft wird auf den verschobenen Zeilen:
  - Fahrten in 0..Verfahrweg;
  - Laserbahnen in der 30-mm-Safezone;
  - danach der normale Preflight (Laser-Guard).

  Relative X/Y-Aufträge werden nicht verschoben.
- Die Platzierung liegt im Speicher (nicht persistent). Sie gilt für
  `start`/`autorun`/`frame` mit `placement=1`. Sie verfällt bei neuem
  Upload oder Löschen, bei `current` auch nach `home`/`jog`/`moveto`.
- Der Benutzer-Ursprung steht in `marlin.json` (`user_origin`).
- Ohne Platzierung bleibt alles absolut (LightBurn, Web-UI, ältere Studio).
  Die Pi-Web-UI hat keinen Ursprungs-Knopf.
- ⚠ Hardware.

### Parken (`op=park`)

- Dieselbe Routine wie LightBurn `M2` und das Auftragsende: Laser aus,
  Z-Rückzug (nie abwärts), X0/Y0.
- ⚠ Hardware (über die API).

### Status (`GET /api/status`)

- **Snapshot statt Blockieren:** `machine_snapshot()` wartet höchstens
  0,25 s auf `machine.lock`. Ist die Sperre belegt (Home, Park, Abtasten, `moveto`,
  Rahmenkante), kommt der letzte vollständige Status. Live überlagert
  werden `state`, `owner`, `homed`, `z_homed`, `emergency_latched`,
  `laser_armed`, `laser_cooling_fan_on`, `position`, `fault`,
  `workpiece_surface_z` und `connected`.
- Dazu kommen `busy: true` und `stale_ms` (Alter des gecachten Teils,
  `null` ohne Cache). Frei: `busy: false`, `stale_ms: 0`.
- `position` ist dabei die zuletzt von Marlin gemeldete Position, keine
  Live-Interpolation.
- ⚠ Hardware (Test: `test_status_never_blocks_behind_long_move`).

### SKR-Firmware flashen (`/api/firmware`)

- Über USB mit Marlin `BINARY_FILE_TRANSFER` (`M28 B1`) nach
  `firmware.bin` auf der SD des SKR, dann `M997`. Der BTT-Bootloader
  flasht.
- Bild höchstens 256 KB − 28 KB (`MAX_IMAGE`), wird validiert. Nicht
  während eines Auftrags und nur ohne Besitzer.
- Die alte Firmware muss Binärübertragung können, sonst einmal per
  SD-Karte flashen.
- Fortschritt in `/api/status` → `firmware_update`.
- Ob das an der echten Maschine getestet ist, steht nirgends im Code.
  Siehe [FIRMWARE.md](FIRMWARE.md).

### Kamera und `op=moveto`

- `moveto` (`transport.move_to`) ist nur gehomed und mit Laser aus
  möglich: erst `M5 I`, dann `M400`, `M114`. Z wird höchstens auf die
  Rückzugshöhe angehoben, nie abgesenkt. XY darf wie beim Parken durch die
  Safezone.
- Der Kamera-Snapshot liest per `ffmpeg -f v4l2` mehrere Bilder (wegen der
  Belichtung) und gibt das letzte als JPEG zurück. Timeout 15 s.
- `/api/status` → `camera` zeigt nur, ob das Gerät existiert.
- Kalibrierung (`camera_calibration.py`): JSON-Datei auf dem Pi, atomar
  geschrieben, Revision gegen gleichzeitiges Speichern. Bei alten
  Installationen (Dienstdatei ohne `ReadWritePaths=-/etc/lumacut`) landet
  sie in `/var/lib/lumacut`, bis `install.sh` erneut läuft.
- ⚠ Hardware.

### Hintergrund

- Der Monitor-Thread verbindet das SKR alle 8 s neu, falls es getrennt ist.
- Er sendet alle 2 s einen M114-Heartbeat (nur wenn frei). `command()`
  setzt dabei **keinen** Besitzer.
- Er erledigt auch den Lüfternachlauf.

## 2. Was für `op=frame` und `op=park` aktualisiert sein muss

| Funktion | Commit (auf `main`) | Dateien |
|---|---|---|
| `op=park` | `eaa3f38` feat(pi400): op=park in /api/action (Laser aus, Z-Rückzug, X0/Y0) | `pi400/marlin/web.py` |
| `op=frame` | `65a22b4` feat(pi400): op=frame Rahmenfahrt ohne Laser, ohne den hochgeladenen Auftrag zu ersetzen. Tests: `f5b8ab2` | `pi400/marlin/web.py`, `tests/test_marlin_gateway.py`, `docs/PI_BETRIEB.md` |
| Status-Snapshot (`busy`, `stale_ms`) | fix(pi400): /api/status blockiert nicht mehr hinter langen Fahrten (siehe `git log --grep="blockiert nicht mehr"`) | `pi400/marlin/web.py`, `tests/test_marlin_gateway.py` |
| `op=moveto`, `/api/camera/snapshot`, `camera` im Status | `2c61b8a` (Kamera-Scan) | `pi400/marlin/web.py`, `pi400/marlin/transport.py` |
| Auftrags-Ursprung (`op=place`, `origin_set`, `origin_clear`, `place_clear`, `placement=1`, Status `origin`) | „feat(pi400): Auftrags-Ursprung …“ (`git log --grep="Auftrags-Ursprung"`) | `pi400/marlin/placement.py`, `pi400/marlin/web.py`, `tests/test_job_placement.py` |

Es reicht, den Pi-Dienst zu aktualisieren (Python-Code). SKR-Firmware,
`/etc/lumacut` und die Daten bleiben gleich.

**So erkennt man einen veralteten Pi** (`curl http://lumacut.local:8080/api/status`):

- `frame` und `activity` fehlen: kein `op=frame`.
- `busy` und `stale_ms` fehlen: kein Status-Snapshot; der Status hängt
  während Home/Park/Abtasten.
- `origin` fehlt: keine Ursprungs-Optionen. Studio sperrt die Auswahl und
  startet nur absolut.
- `op=park` lässt sich am Status nicht erkennen. Ein Pi ohne `frame` ist
  aber älter als `65a22b4` und kann auch älter als `eaa3f38` sein.

**Meldungen in Studio** (`software/lumacut-studio-native/src/machine/client.py`):

- Parken: „Pi-Dienst bietet noch kein Parken über die API (op=park fehlt
  in pi400/marlin/web.py)“.
- Rahmen: „Pi-Dienst bietet noch keine Rahmenfahrt über die API (op=frame
  fehlt in pi400/marlin/web.py – Pi aktualisieren)“.
- Ursprung: „Pi-Dienst kennt noch keine Ursprungs-Optionen (op=place
  fehlt in pi400/marlin/web.py – Pi aktualisieren)“. Im Panel steht „Pi-Dienst
  zu alt: nur absolute Aufträge – Pi aktualisieren“.
- Alle werden aus der Pi-Antwort 400 „Unbekannte Marlin-Aktion: …“
  übersetzt.
- Ohne Snapshot zeigt Studio „Status N s alt“ statt „Pi fährt“ und sperrt
  so lange alle Knöpfe außer NOT-AUS.

## 3. Pi aktualisieren: Schritte

Pfade laut `install.sh`: Programm `/opt/lumacut`, Dienst
`lumacut-marlin.service`, Konfiguration `/etc/lumacut/lumacut.env`.
Vorher LightBurn trennen und keinen Auftrag laufen lassen.

```bash
ssh <benutzer>@lumacut.local            # oder die IP, z. B. 192.168.2.89

# 1) Empfohlen: der eingebaute Updater (nur Fast-Forward, prüft Syntax,
#    Import und HTTP, rollt bei Fehlern selbst zurück)
sudo bash /opt/lumacut/pi400/update.sh diagnose   # nur anzeigen
sudo bash /opt/lumacut/pi400/update.sh            # aktualisieren

# 2) Alternativ von Hand (wie update.sh, ohne dessen Absicherungen)
cd /opt/lumacut
sudo -u lumacut git status --short               # muss leer sein
sudo -u lumacut git rev-parse --short HEAD       # alten Stand notieren
sudo -u lumacut git pull --ff-only https://github.com/theubyte/LumaCut-CNC.git main
sudo systemctl restart lumacut-marlin.service

# 3) Prüfen
systemctl is-active lumacut-marlin.service
sudo journalctl -u lumacut-marlin.service -n 50 --no-pager
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool | grep -E '"(frame|activity|busy|stale_ms|owner|origin)"'
```

- Erwartet: `frame`, `activity`, `busy`, `stale_ms` und `origin` sind vorhanden,
  `owner` ist „Frei“.
- Danach in Studio „Verbinden“ und einmal Rahmen und Parken probieren
  (vorher referenzieren, Laser getrennt).
- **Abhängigkeiten:** Für Rahmen, Parken und Status nichts Neues. Es
  reichen die Pakete aus `install.sh` (`python3-flask`, `python3-serial`),
  kein `pip`.
- **Optional, nur für die Kamera** (`/api/camera/snapshot`): `ffmpeg`.
  `install.sh` installiert es **nicht**:
  `sudo apt-get install -y ffmpeg`. Ohne `ffmpeg` antwortet der Endpunkt
  mit 503 „Kamera antwortet nicht“. Der Dienst läuft bereits mit der
  Gruppe `video`.
- **Zurückrollen** (Hand-Variante): Den Hash `<alt>` von oben verwenden.
  `update.sh` macht das bei fehlgeschlagenem Start automatisch.

  ```bash
  sudo systemctl stop lumacut-marlin.service
  sudo -u lumacut git -C /opt/lumacut reset --hard <alt>
  sudo systemctl start lumacut-marlin.service
  ```

  Achtung: Das nächtliche Update (`lumacut-update.timer`, ~04:15) zieht
  danach wieder `main`. Zum dauerhaften Festhalten den Timer stoppen:
  `sudo systemctl disable --now lumacut-update.timer`.
- **Notfall** (kaputter Git-Checkout): `pi400/recover.sh`, siehe
  [PI_BETRIEB.md](PI_BETRIEB.md#updates).

## 4. Offene Punkte

1. **`X-LumaCut-Key` wird nicht geprüft (bewusst).** Die Web-UI ist ohne
   Anmeldung (Commit `78ce258`, Hinweis in `index.html`, Test
   `tests/test_marlin_gateway.py` prüft „Keine Anmeldung erforderlich“).
   Jeder im WLAN kann die Maschine bedienen. Schutz ist nur das WLAN;
   Port 8080 nicht ins Internet freigeben. Eine Schlüsselprüfung würde die
   Web-UI aussperren und braucht eine eigene Entscheidung.
2. **Status-Verzögerung: gelöst** durch den Snapshot (`busy`/`stale_ms`).
   Das gilt erst ab dem aktualisierten Pi, siehe Abschnitt 2.
3. **Kein Rahmen- und kein Park-Knopf in der Pi-Web-UI.** `index.html`
   bietet `connect`, `info`, `position`, `endstops`, `home`, `probe`,
   `start`, `autorun`, `abort`, `estop`, `estop_reset`, Jog, Licht und
   Abluft. Rahmen, Parken, `moveto` und Kamera gibt es nur über die API
   (Studio, Tablet).
4. **Kein HTTPS:** Alles läuft unverschlüsselt im LAN (HTTP 8080, TCP 23).
5. **CI:**
   - Der Workflow `ci.yml` („LumaCut Pi 400 tests“) installiert
     `Flask==3.1.1` und `pyserial==3.5` und führt
     `python -m unittest discover -s tests` aus.
   - Die Flask-Tests werden dort also **nicht** übersprungen; in `tests/`
     gibt es kein `skip`.
   - Er läuft aber nur bei Änderungen unter `pi400/**`, `tests/**`,
     `firmware/marlin/**` oder an der Workflow-Datei.
   - Der Windows-Workflow `lumacut-studio-native.yml` testet nur die App
     (gegen `tests/fake_pi.py`), nicht den echten Pi-Code.
6. **Nicht an echter Hardware nachgewiesen (⚠):**
   - Rahmenfahrt (`op=frame`), Parken über die API (`op=park`) und der
     Status-Snapshot während echter Fahrten.
   - Upload großer Aufträge über WLAN (Studio-Zeitlimit 120 s + 10 s/MB).
   - Die Studio-Anbindung insgesamt gegen den echten Pi.
   - Firmware-Flash über USB (kein Nachweis im Repo).
   - Kamera-Snapshot und `op=moveto`.
   - Platzierte Aufträge (`op=place`): Lage auf dem Material und Rahmen am
     Ursprung.
7. **Prüfergebnisse (Audit, kein akuter Fehler):**
   - `/api/settings` nimmt `machine.lock` und wartet daher hinter einer
     laufenden Fahrt. Die Antwort kommt erst danach; das ist harmlos, aber
     langsam.
   - `/api/jobs/<name>/geometry` prüft den Namen, aber nicht die Endung
     (anders als `content`/`delete`). Das ist unkritisch, weil nur
     `JOBS/` lesbar ist.
   - Der Lüfternachlauf hängt am Pi-Prozess. Stürzt der Dienst ab, entfällt
     der Nachlauf (steht so in `/api/status` → `io.fan_cooldown`).
   - Im Snapshot ist `position` die letzte M114-Antwort. Während einer
     langen Kante bewegt sie sich nicht.
   - `install.sh` installiert `ffmpeg` nicht, obwohl
     `/api/camera/snapshot` es braucht. Das fällt in den Bereich Kamera;
     dort entscheiden.
   - Abbrechen wirkt bei Rahmen an der **nächsten Ecke**, nicht mitten in
     der Kante. Sofort stoppt nur NOT-AUS.
