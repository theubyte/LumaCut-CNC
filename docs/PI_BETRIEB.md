# Pi 400: Betrieb, Updates, API

## Dienste und Dateien

| | |
|---|---|
| Dienst | `lumacut-marlin.service` (Benutzer `lumacut`, `python3 -m marlin.web`, `Restart=always`) |
| Programm | `/opt/lumacut` (Git-Clone von `main`, gehört `lumacut`) |
| Konfiguration | `/etc/lumacut/lumacut.env` (Ports, Datenpfad), `/etc/lumacut/lumacut-marlin-port.env` (fester SKR-Pfad `/dev/serial/by-id/usb-LeafLabs_Maple-if00`) |
| Daten | `/var/lib/lumacut/marlin/config.json` (Kalibrierung), `/var/lib/lumacut/marlin/jobs/` (hochgeladene Aufträge) |
| Ports | 8080 Web-UI/API, 23 TCP für LightBurn |
| Auto-Update | `lumacut-update.timer`, täglich ~04:15 → `pi400/update.sh` |

## Installation (neuer Pi)

```bash
git clone https://github.com/theubyte/LumaCut-CNC.git
sudo bash LumaCut-CNC/pi400/install.sh
```

Das Skript installiert Pakete, verschiebt das Repository nach `/opt/lumacut`, erkennt das SKR per `M115` und speichert seinen festen USB-Pfad. Es deaktiviert einen alten GRBL-Dienst, falls vorhanden, und richtet Dienst und Update-Timer ein. Es flasht nie das SKR.

## Updates

- **Automatisch:** Jede Nacht holt `update.sh` den aktuellen `main` per HTTPS (nur Fast-Forward). Es prüft Syntax und Import und startet den Dienst neu. Klappt etwas nicht, geht es auf den alten Commit zurück. Es aktualisiert nicht, solange LightBurn verbunden ist oder ein Auftrag läuft.
- **Sofort:** `sudo bash /opt/lumacut/pi400/update.sh` (Diagnose ohne Änderung: `… update.sh diagnose`).
- **Ohne GitHub (Entwicklung per SSH):**
  ```bash
  git push ssh://lumacut@192.168.2.89/opt/lumacut main:refs/heads/incoming
  ssh lumacut@192.168.2.89 'cd /opt/lumacut && git merge --ff-only incoming && git branch -D incoming'
  sudo systemctl restart lumacut-marlin.service   # auf dem Pi
  ```
  Danach trotzdem nach GitHub pushen, sonst weicht der Pi von `main` ab und das nächtliche Update bricht ab (nicht Fast-Forward).
- **Notfall** (kaputter Git-Checkout, Dienst startet nicht):
  ```bash
  curl -fsSL https://raw.githubusercontent.com/theubyte/LumaCut-CNC/main/pi400/recover.sh -o /tmp/recover.sh && sudo bash /tmp/recover.sh
  ```
  Klont frisch, sichert vorher `/etc/lumacut` und `/var/lib/lumacut`.

Die SKR-Firmware wird nie automatisch aktualisiert, siehe [FIRMWARE.md](FIRMWARE.md).

## Bedienung (Web-UI `http://lumacut.local:8080`)

- **XYZ referenzieren:** X/Y, dann Z, dann Rückzug 20 mm, danach die Melodie.
- **Melodien:** nach dem Referenzieren, beim Auftragsstart (nach dem Abtasten, vor dem ersten Laserweg) und am Auftragsende. Die Motoren singen über die Spulen, der Kopf bewegt sich dabei nicht (Firmware-Befehl `M300`, siehe [FIRMWARE.md](FIRMWARE.md)). Bei Alarmen gibt es bewusst keine Töne. Ältere Firmware ohne diesen Befehl spielt einfach nichts.
- **Werkstück abtasten (G30):** unter der aktuellen Laserposition.
- **Aufträge:** `.gcode` hochladen. Beim Hochladen prüft der Pi jede Zeile und ob das Motiv in der Safezone liegt.
  - „Auftrag starten“ setzt voraus, dass schon referenziert und abgetastet ist.
  - **Automatischer Auftrag (`op=autorun`, „Starten“ in den Apps)** macht alles: Referenzieren nur wenn nötig, Abtasten mit kleinem Raster über allen Motivbereichen (niedriger 3-mm-Hub zwischen den Punkten, tiefster Punkt zuletzt nochmal), Höhenkorrektur auf dem Pi (der Fokus folgt der Oberfläche), Auftrag, Parken, Melodie. Unter dem Motiv muss Material liegen; Punkte, die der Taster nicht erreicht, ergänzt der Pi aus den Nachbarn. Details: [PI_API_REFERENZ.md](PI_API_REFERENZ.md) `op=autorun`.
- **Material-Datenbank:** `/var/lib/lumacut/materials.json`, eine Liste für alle Programme (`/api/materials`). Beim ersten Start legt der Pi Startwerte an. Sicherung: die Datei mitkopieren.
  - **„Auftrag abbrechen“** schaltet den Laser aus und parkt. M112 kommt nur, wenn das nicht mehr klappt.
- **Rahmenfahrt (aus LumaCut Studio, `op=frame`):** fährt den Umriss des Designs mit ausgeschaltetem Laser ab. Rechteck oder Gummiband (konvexe Hülle).
  - Setzt Referenzfahrt und Leerlauf voraus. Wird abgelehnt, während ein Auftrag läuft oder LightBurn verbunden ist.
  - Der hochgeladene Auftrag, die Auftragsliste und der Auftragsstatus bleiben unverändert. Danach also direkt „Auftrag starten“, ohne neu zu senden.
  - Der Pi nimmt nur `G0`/`G1` mit X/Y (Leistung höchstens `S0`), `G21`, `G90`, `M5 I`, `M400` an. Kein `M3`, kein Z, nur Punkte im Verfahrbereich.
  - „Auftrag abbrechen“ stoppt an der nächsten Ecke, M112 stoppt sofort. Es wird nicht geparkt.
- **Software-Notstopp M112:** Danach das SKR zurücksetzen (Reset-Taste oder kurz stromlos) und „Notstopp quittieren“ drücken. Der Pi gibt erst frei, wenn das SKR wieder antwortet.
- **SKR-Firmware:** `.bin` auswählen, „Flashen“ (siehe [FIRMWARE.md](FIRMWARE.md)).

Nur ein Bediener gleichzeitig: Ist LightBurn verbunden, lehnt der Pi Befehle aus Web und Studio ab (und umgekehrt).

## LightBurn (Übergangsphase)

Bis LumaCut Studio alles kann, funktioniert LightBurn weiter:
- Gerät **Marlin**, Verbindung **TCP/Netzwerk**, Adresse `lumacut.local`, Port 23. S-Wert-Maximum **255**.
- Start-G-Code `G21` / `G90`, Laser über `M3 I`. Kein `M4`, keine GRBL-Befehle (`$H`, `$$`, `?`).
- `G28` löst die Pi-Referenzfahrt aus, `G30` das Abtasten, `M2` das Parken mit Melodie.
- LightBurn behandelt S als dauerhaft gültig, Marlin setzt die Leistung nach jedem `G0` auf 0. Fehlt der S-Wert im ersten `G1` nach einer Leerfahrt, setzt der Pi den letzten Wert ein.

## HTTP-API (für Studio und Tablet)

Kurzübersicht. Vollständige Referenz mit Parametern, Fehlern, Sperren, Statusschema und Beispielen: [PI_API_REFERENZ.md](PI_API_REFERENZ.md).

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | Zustand: Verbindung, Besitzer, Position, homed, Ursprung (`origin`), Warteschlange (`queue`), Werkstück-Z, Fokus-Z, Job, Rahmen (`frame`), Tätigkeit (`activity`: `idle`/`job`/`framing`), `busy`/`stale_ms` (Snapshot, blockiert nicht hinter Fahrten), Firmware-Update, Konfiguration |
| POST | `/api/action` `op=…` | `home`, `park`, `jog` (`axis`, `distance` ∈ ±0,1/1/10), `probe` (optional `x`,`y`), `light`/`exhaust` (`on`), `start`/`autorun` (`name`, optional `x`,`y` als Abtastpunkt), `frame` (`gcode`, `mode`=`box`/`hull`), `moveto` (`x`,`y` Maschinen-mm; Laser aus, hebt Z nur an – für den Kamera-Scan), Ursprung: `origin_set` (`x`,`y` oder Kopf), `origin_clear`, `place` (`name`, `origin`=`absolute`/`current`/`user`, `anchor`=`tr`(Standard, Schalterecke)/`tl`/`bl`/`br`/`center`, Ecken von vorne gesehen, X0/Y0 oben rechts), `place_clear`; `start`/`autorun`/`frame` mit `placement=1` laufen platziert, ohne absolut, Warteschlange: `queue_add` (`name`, `origin`/`anchor` oder `placement=1`), `queue_run`, `queue_pause`, `queue_skip`/`queue_remove` (`id`), `queue_clear`, `abort`, `estop`, `estop_reset`, `connect`, `info`/`position`/`endstops` |
| POST | `/api/upload` | Auftrag (`file`, `.gcode`/`.gc`/`.nc`), wird vorab geprüft |
| GET | `/api/jobs`, `/api/jobs/<name>/geometry`, `/api/jobs/<name>/content` | Aufträge, Motivgrenzen, Roh-G-Code |
| POST | `/api/jobs/<name>/delete` | Auftrag löschen (nicht den laufenden) |
| POST | `/api/settings` | Fokus, Rückzug, Schalter→Spitze, Tasterversatz |
| POST | `/api/commission` | Mechanik-Freigabe (einmalig nach Inbetriebnahme) |
| GET | `/api/camera/snapshot?w=&h=` | JPEG von der Kopfkamera (`LUMACUT_CAMERA`, Standard `/dev/video0`); ohne Kamera 503. Verfügbarkeit in `/api/status` → `camera` |
| GET/PUT | `/api/camera/calibration` | Kamera-Kalibrierung der Maschine (`/etc/lumacut/camera_calibration.json`, überschreibbar mit `LUMACUT_CAMERA_CALIBRATION`); PUT nur JSON mit `revision`, 409 bei Konflikt – Details: [KAMERA_STATUS_UND_KALIBRIERUNG.md](../software/lumacut-studio-native/docs/KAMERA_STATUS_UND_KALIBRIERUNG.md#3a-kalibrierung-auf-dem-pi-speichern) |
| POST | `/api/firmware` | SKR-Firmware (`file`), Fortschritt in `/api/status` → `firmware_update` |

Fehler kommen als HTTP 4xx/5xx mit `{"error": "…"}` in Klartext zurück.

Stand des Dienstes, Update für Rahmen/Parken und offene Punkte: [PI_STATUS_UND_OFFENE_PUNKTE.md](PI_STATUS_UND_OFFENE_PUNKTE.md).

## Fehlersuche

```bash
sudo journalctl -u lumacut-marlin.service -n 80 --no-pager    # Dienst
journalctl -k --since "-1h" | grep -i usb                     # USB-Abbrüche des SKR
sudo bash /opt/lumacut/pi400/update.sh diagnose               # Updater-Sicht
```

- „Steuerung belegt durch lightburn“: LightBurn trennen.
- „M112-Notstopp verriegelt“: SKR zurücksetzen, dann „Notstopp quittieren“.
- Raster ruckelt oder Marlin meldet Fehler mitten im Raster: Job-Streaming testweise abschalten mit `LUMACUT_STREAM_WINDOW=1` in `/etc/lumacut/lumacut.env`, dann `sudo systemctl restart lumacut-marlin.service`. Standard sind 4 Zeilen ohne `ok` unterwegs; `/api/status` → `stream_window` zeigt den Wert.
- Plötzliche USB-Abbrüche („USB disconnect“ im Kernel-Log) mitten im Betrieb deuten auf Kabel oder Versorgung hin. Mitten im Job ist das kritisch.
