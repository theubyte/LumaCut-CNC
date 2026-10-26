# Scan & Probe: Kamera-Scan, Höhenmesh, Ein-Klick-Auftrag

Stand 2026-10-26, Scan-Probe-Agent. Bezug: `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md`
§1, §3 und §7; Pi-Vertrag `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` §4.
Code: `software/lumacut-studio-native/src/scanprobe/`.

Vertragskennung: `lumacut-scanprobe/1` (`scanprobe/contract.py`, `CONTRACT`).

> Ehrlich: Alles hier ist nur mit Simulation und Fakes getestet. An der echten
> Maschine ist der Ein-Klick-Ablauf noch nicht gelaufen.

## 1. Bedienung in Studio

- **Hauptansicht:** ein Knopf **„Kamera-Scan“**. Optional, kein Pflichtschritt.
  - Ist der Pi verbunden und hat der Nutzer keinen Modus gewählt, scannt Studio mit der Maschine.
  - Sonst läuft der Scan in der Simulation.
  - Das Ergebnis wird Hintergrund im Canvas. Daneben stehen Pause, Abbrechen und der Fortschritt.
- **„Mehr …“** (eingeklappt): Modus, Kamera, Kalibrierung, Rasterabstand, „Nur Höhenmesh messen“,
  „Scan + Höhenmesh“, Werkstückliste, Bereiche markieren, Höhenkarte anzeigen,
  Mesh speichern/laden/wiederverwenden, G-Code-Export, „Ein-Klick-Auftrag starten“.
- **Keine Auswahl „mit/ohne Höhenmesh“ mehr.** Der Haken „Fokuskorrektur“ ist entfernt.
  - Liegt ein Höhenmesh vor, wird jeder gesendete oder exportierte Auftrag automatisch fokuskorrigiert (`ScanPanel.prepare_job_gcode`).
  - Fehler, ein zu altes Mesh oder die Pi-Sperre stoppen das Senden mit einem Satz und dem nächsten Schritt.
  - Für Fachleute und Tests gibt es nur das versteckte Attribut `skip_focus_correction`.

## 2. Ein-Klick-Auftrag

`scanprobe/job_flow.py` (Qt-frei) und `scanprobe/job_flow_qt.py` (Thread, Panel-Anbindung).

Ablauf, ohne Rückfragen nach der einen Bestätigung „Auftrag starten?“:

| Schritt | `state` | Was passiert |
|---|---|---|
| 1 | `referenzieren` | `op=home`, nur wenn der Pi „nicht referenziert“ meldet |
| 2 | `probing` | Messbereiche aus der **Brennstrecke des Auftrags** (Abstand < 6 mm → ein Bereich, +3 mm Rand) plus erkannte Werkstücke aus einem optionalen Scan. Grobes Raster 25 mm, adaptiv verfeinert (`FAST_PROBE`). Ein frisches Mesh, das den Auftrag abdeckt, wird nach Bildvergleich und 3 Kontrollpunkten je Bereich wiederverwendet. |
| 3 | `fokus` | `op=focus` (G30) am **niedrigsten** Messpunkt, damit die Pi-Sperre „letztes G30 + 2 mm“ unter allen Fokushöhen liegt. Danach Fokuskorrektur mit allen Prüfungen: keine Bögen, kein absolutes Z, Material nicht bewegt, Pi-Sperre. |
| 4 | `job` | Hochladen, `op=start`, Fortschritt aus `/api/status` |
| 5 | `parken` | Der Pi parkt am Auftragsende selbst. Bei Fehler oder Abbruch **vor** dem Lasern ruft Studio `op=park`. |

- **Ist ein Pi mit Merkmal `autorun_mesh`** (siehe §5) verbunden, macht der Pi die Schritte 1–3 selbst.
  - Studio lädt dann den unkorrigierten Auftrag hoch und startet `op=autorun`.
  - `job.state`/`job.probe` werden in dieselben Zustände übersetzt.
- **Pause** wirkt zwischen zwei Maschinenschritten (Messpunkte), nicht während des Laserns.
- **Abbrechen:**
  - Vor dem Lasern: anhalten und parken.
  - Beim Lasern: `op=abort`, der Pi schaltet den Laser aus und parkt.
- **Studio schließen:** Ein laufender Auftrag wird nicht abgebrochen, Studio hört nur auf zu beobachten.
- **Ursprung:** Der Ein-Klick-Auftrag verlangt Ursprung „Absolut“, weil das Mesh in Maschinen-mm liegt. Siehe offene Fragen.

## 3. Nachrichten (JSON, für Studio, Pi-Web-UI und später Android)

Alle Koordinaten sind Maschinen-mm (Laserpunkt), Zeiten Sekunden, Texte deutsch.
Jede Nachricht hat `type`. Unbekannte Felder ignorieren.

`job_state` (bei jeder Zustandsänderung und bei Fortschritt):
```json
{"type": "job_state", "state": "probing", "label": "Höhenmesh messen", "step": 2, "steps": 5,
 "message": "Messpunkt 4/12", "progress": 0.33, "paused": false, "eta_s": 21.0}
```
- Zustände: `bereit`, `referenzieren`, `probing`, `fokus`, `job`, `parken`, `fertig`, `fehler`, `abgebrochen`.
- Bei `fehler` gibt es zusätzlich `"error": {"code": "...", "message": "..."}`.
- Fehlercodes: `not_ready`, `invalid_job`, `homing_failed`, `probe_failed`, `focus_failed`, `upload_failed`, `job_failed`, `emergency`, `connection_lost`, `cancelled`, `detached`.

`job_result` (am Ende):
- Felder: `state`, `ok`, `job`, `reused_mesh`, `pi_mesh`, `probe_points`, `areas`, `focus_point`, `z_range`, `error`, `notes`, `durations_s`.

`scan_progress`:
- Felder: `phase`, `done`, `total`, `progress`, `message`, `eta_s`.
- `phase` ist eines von `scan`, `stitch`, `detect`, `probe`, `verify`.

`scan_result`:
- Felder: `contract`, `mosaic` (Metadaten: mm pro Pixel, Ursprung, Größe), `objects` (`id`, `kind`, `bounds`, `center`, `area_mm2`, `confidence`).
- Optional `image_png_base64`.

`error`: `code`, `message`.

Anfragen:
- `scan_request`: `camera` (`pi` oder `local`), `bounds` (`[x0, y0, x1, y1]` oder `null`), `overlap` (0.05–0.6).
- `job_request`: `name` (`*.gcode`/`.nc`/`.gc`), `gcode`, `reuse_mesh`.
- Prüfung mit deutschen Fehlermeldungen: `contract.parse_scan_request` / `parse_job_request`.

### Vorgeschlagene HTTP-Endpunkte (noch **nicht** gebaut)

Für eine spätere Android-App oder Pi-Web-UI. Wo der Dienst läuft (Pi oder Studio), ist offen.

| Endpunkt | Zweck |
|---|---|
| `POST /api/scan` | Kamera-Scan starten (`scan_request`) → `scan_progress` … |
| `GET /api/scan` | letztes `scan_progress` bzw. `scan_result` |
| `GET /api/scan/mosaic.png` | Mosaikbild (PNG), Metadaten in `scan_result.mosaic` |
| `POST /api/scan/cancel` | Scan abbrechen |
| `POST /api/oneclick` | Ein-Klick-Auftrag starten (`job_request`) → `job_state` … |
| `GET /api/oneclick` | letztes `job_state` bzw. `job_result` |
| `POST /api/oneclick/pause` | Pause zwischen zwei Maschinenschritten |
| `POST /api/oneclick/resume` | Fortsetzen |
| `POST /api/oneclick/cancel` | Abbrechen |

Für Android reicht auf einem Pi mit `autorun_mesh` schon heute der Pi-Vertrag §4:
- Hochladen, dann `op=autorun`.
- `/api/status` abfragen und mit derselben Tabelle wie oben in `job_state` übersetzen (`homing` → `referenzieren`, `probing` → `probing`, `running` → `job`, `complete` → `fertig`).

## 4. Was Studio von der Maschine braucht (`MachinePort`)

Die Schnittstelle ist bewusst klein. `ClientMachinePort` bildet sie auf `machine.client.LumaCutClient` ab, ohne diesen zu ändern:

| Methode | Pi |
|---|---|
| `status()` | `/api/status` → `homed`, `emergency_latched`, `workpiece_surface_z`, `job` (`state`, `file`, `line`, `total`, `error`, `active`), optional `features`, `job.probe` |
| `home()` | `op=home` |
| `probe_at(x, y)` | `op=focus x= y=` (G30 am Punkt) |
| `upload_job(name, gcode)` | `POST /api/upload` |
| `start_job(name)` | `op=start` (absolut) |
| `autorun(name)` | `op=autorun` (nur wenn `autorun_mesh` gemeldet) |
| `abort_job()` | `op=abort` |
| `park()` | `op=park` (ältere Pi-Dienste kennen es nicht; dann Hinweis statt Fehler) |

Messfahrten für das Höhenmesh laufen über den Mess-Workflow (`ScanProbeWorkflow`, Pi-Adapter `adapters.pi_setup`) wie beim Knopf „Nur Höhenmesh messen“.

## 5. Offene Punkte

- **Pi (Claude):**
  - `/api/status` soll `features: ["autorun_mesh"]` melden, sobald `op=autorun` selbst abtastet und korrigiert.
  - Während des Abtastens soll `job.probe: {"done", "total"}` kommen.
  - Ohne das Merkmal misst Studio selbst (heutiger Stand).
- **Machine-Agent:**
  - Start-Knopf der Werkzeugleiste auf `self.one_click.start` umstellen (eine Zeile in `main.py`, Machine-Block).
  - Klären, ob Platzierung (`origin` ≠ absolut) mit Mesh gehen soll. Dafür müsste das Mesh mit verschoben werden, oder der Pi tastet nach der Platzierung ab (bei `autorun_mesh` automatisch richtig).
  - `op=park` auf älteren Pi-Diensten.
- **Canvas-Agent:** Bilder spiegeln, wenn der Canvas auf Nullpunkt oben rechts umstellt (Anforderungen §2.1). Betrifft `mosaic_to_work_image` und die Höhenkarte.
- **Android:** Es gibt keinen Android-Code von Scan Probe. Der Vertrag oben ist die Vorbereitung.
