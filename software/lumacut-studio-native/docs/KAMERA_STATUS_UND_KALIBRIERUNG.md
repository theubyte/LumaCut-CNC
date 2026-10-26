# Kamera am Laserkopf: Ist-Stand und Kalibrierung

Stand: 26.10.2026, Branch `main` (geprüft gegen Code und Doku im Repo, nicht an der Maschine).
Zurück zur Übersicht: [SCAN_PROBE.md](SCAN_PROBE.md) · Kalibrierablauf: [KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md)

**Kurzfassung:** Die Kamera-Software (Kachel-Scan, Stitching, Objekterkennung, Kalibriermodell,
Studio-Oberfläche) ist implementiert und mit **synthetischen Bildern** getestet. Mit einer
echten Kamera ist bisher **nichts** gelaufen: Kameramodell und Anschluss sind unbekannt, alle
Kalibrierwerte sind Platzhalter. Seit `2c61b8a` hat der Pi einen Snapshot-Endpunkt und `op=moveto`;
seit 26.10. scannt Studio im Maschinen-Modus darüber (Kamera „Pi (Snapshot)", XY per moveto,
Rückfall auf Jog-Schritte und lokale Kamera bei altem Pi) – nur gegen einen Fake-Pi getestet. Die **Kalibrierung liegt seit 26.10. auf dem Pi**
(`/etc/lumacut/camera_calibration.json`, `GET/PUT /api/camera/calibration`, Abschnitt 3a);
`camera.json` ist nur noch Import/Export und Rückfall für Simulation/offline.

Legende: **erledigt** = im Code vorhanden und automatisch getestet · **offen** = fehlt ·
**ungeprüft** = vorhanden, aber nie mit echter Hardware/auf dem Zielsystem gelaufen.

## 1. Wie die Kamera heute angebunden ist

| Teil | Stand | Quelle |
|---|---|---|
| Kamera-Zugriff in Studio | Auswahl im Scan-Panel: **„Pi (Snapshot)"** (`PiSnapshotCamera`, Standard, wenn der Pi Snapshot und Kamera meldet) oder **„Lokal (USB/URL)"**. Lokal: `OpenCvCamera`: `cv2.VideoCapture(Quelle)`; Quelle = USB-Index (`0`) oder Stream-URL. Setzt Auflösung und (optional) feste Belichtung aus `camera.json`, verwirft vor jeder Aufnahme 2 gepufferte Bilder. **ungeprüft** – nie mit echter Kamera gelaufen. | `src/scanprobe/adapters.py` |
| Wo die Kamera hängt | „Pi (Snapshot)": Kamera am Pi (V4L2), Studio holt je Kachel ein JPEG. „Lokal": Kamera wird **von Studio (PC/Tablet) direkt** geöffnet. Eine Stream-URL wie `http://lumacut.local:8081/stream` steht nur als Beispiel im Tooltip – auf dem Pi läuft **kein** solcher Dienst. | `panel.py`, `adapters.py` |
| Kamera auf dem Pi | `GET /api/camera/snapshot?w=&h=` liefert ein JPEG (`ffmpeg`, V4L2-Gerät `LUMACUT_CAMERA`, Standard `/dev/video0`), `/api/status` → `camera` meldet nur, ob das Gerät existiert (seit `2c61b8a`). **ungeprüft** mit echter Kamera. Studio (`PiSnapshotCamera`) fragt die Bildgröße der Kalibrierung an (Pi erlaubt 160–4096 × 120–3072), wiederholt bei 503/Netzfehler/kaputtem JPEG zweimal, meldet 404 (alter Pi) und abweichende Bildgröße sofort. Belichtung aus der Kalibrierung wirkt hier **nicht** (der Pi stellt keine ein, er verwirft nur die ersten 5 Bilder). Die Kalibrierung liegt auf dem Pi (Abschnitt 3a). | `pi400/marlin/web.py`, `camera_calibration.py` |
| Kopfbewegung für den Scan | `PiMachine.move_to`: XY per `op=moveto` (absolut, Laser aus, blockiert bis `M400`, hebt Z auf `z_clearance_mm` an, wenn tiefer; Studio prüft die gemeldete Position auf ±0,2 mm). Z weiter in Jog-Schritten ±10/±1/±0,1 mm (kein absoluter Z-Befehl auf dem Pi). `wait_idle` fragt `/api/status` ab. Rückfall auf Jog-Schritte für XY: alter Pi (kein `camera` im Status, „Unbekannte Marlin-Aktion: moveto") oder Scanhöhe unter der Rückzugshöhe; Hinweis im Panel. Rechnerisch (Standardplan, 12 Kacheln, Fake-Pi): 49 Pi-Anfragen statt 286 (≈ 4 statt ≈ 24 je Kachel); Zeit **nicht gemessen**. **ungeprüft** auf der Maschine. | `adapters.py`, `web.py` |
| Z auf Scanhöhe | Der Scan fährt zuerst Z auf `scan_z` (Platzhalter 40 mm). Laut Pi-Code wird **jede** Z-Fahrt (auch Jog) abgelehnt, solange keine Werkstückoberfläche gemessen ist („Keine Werkstückhöhe bekannt …“). Im Pi-Modus muss also vor dem Scan ein G30/„Fokus“ gelaufen sein – Studio prüft das **vor dem Start** (`check_scan_height`: Oberfläche gemessen, Scanhöhe ≥ Oberfläche + 2 mm, im Fahrbereich Z0..`travels.z`) und meldet es deutsch, ohne zu fahren. Ob `scan_z` = 40 mm im Z-Hub der echten Maschine erreichbar ist, ist **unbekannt**. | `pi400/marlin/transport.py` (`_z_move_guard_locked`) |
| Simulation | `simulated_setup()`: synthetisches Bett (Wabenmuster, Holzmaserung, ein geneigtes Rechteck, eine gewölbte Scheibe), Fake-Maschine mit Positionsfehler 0,3 mm, Fake-Kamera mit dem Platzhalter-Kalibriermodell. Damit laufen Oberfläche und alle Tests ohne Hardware. **erledigt**. | `scanprobe/fakes.py`, `adapters.py` |
| Hardware | **Unbekannt:** Kameramodell, Objektiv/Sichtfeld, Anschluss (USB, CSI am Pi, Netzwerk-Stream), Auflösung, Montageort und Versatz am Kopf, Fokus fest/auto. Bekannt aus dem Code: der Taster hat den Versatz X −23 / Y +15 mm (rechnet der Pi); Fahrbereich 0–390 × 0–370 mm, Arbeitsfläche ab 30 mm (Homing-Sperrzone). | `docs/MASCHINE.md`, `scanprobe/geometry.py` |
| Andere Kamera-Ansätze im Repo | Die ältere Web-/Electron-Studio-Version (`software/lumacut-studio`) hat eine Live-Ansicht mit 4-Punkt-Homographie, die Android-App nutzt die **Tablet**-Kamera als Hintergrund. Beides ist **keine** Kopfkamera und nicht in das native Studio übernommen. | `software/lumacut-studio/README.md`, `docs/ANDROID_APP.md` |

## 2. Kachel-Scan und Objekterkennung

| Modul | Was es tut | Wichtige Parameter |
|---|---|---|
| `tile_scan.py` (`plan_tiles`, `TileScanner`) | Serpentinen-Raster über die Arbeitsfläche bei fester Höhe; erst Z, dann XY; je Kachel `wait_idle` → Ausschwingzeit → Aufnahme → Entzerrung. Nicht erreichbare Randstreifen (Kameraversatz) werden gemeldet. Zeitschätzung vorab. | `overlap` 0–0,8 (Ablauf: 0,25), `settle_s` 0,15 s, Fahrbereich aus `MachineLimits` |
| `stitch.py` (`stitch_mosaic`) | Platziert jede Kachel über die bekannte Kopfposition, Feinkorrektur per Phasenkorrelation (max. ±1,5 mm, nur bei genug Struktur), Belichtungsangleich, mittengewichtetes Überblenden. Ergebnis `Mosaic` (PNG + JSON, mm/px, Ursprung). | `max_refine_mm` 1,5, `min_response` 0,15, `blend_power` 4 |
| `detection.py` (`detect_objects`) | Vordergrund über Leerbett-Referenz **oder** Abstand zum Bett-Median + Otsu (Wabenmuster per Morphologie entfernt); klassifiziert Rechteck (auch gedreht), Kreis, Polygon; Umriss in Maschinen-mm. | `min_area_mm2` 150, `min_size_mm` 8, `texture_mm` 4, Mindestkontrast 18 |
| `calibration.py` (`CameraCalibration`) | Pixel ↔ Maschine (Maßstab, Versatz, Drehung, Spiegelung), Entzerrung, Randbeschnitt, nutzbares Sichtfeld, JSON `lumacut-camera-calibration/1`. | siehe Abschnitt 3 |
| `panel.py`, `pi_calibration.py` | Scan-Panel in Studio: Modus Simulation/Pi, Kamera-Quelle, Kalibrierung vom Pi laden/auf dem Pi speichern, `camera.json` importieren/exportieren, Scan, Mosaik als Canvas-Hintergrund, erkannte Werkstücke als Liste und Overlay, Markieren (seit 26.10.), Auto-Probe, Heatmap. | – |

**Genauigkeit – nur synthetisch geprüft** (`tests/test_scanprobe.py`, Fake-Kamera, Kalibrierung
640×480, 4 px/mm, 1,5° Drehung, Positionsfehler bis 0,4 mm):

* Mosaik deckt > 97 % der Fläche, mittlere Grauwertabweichung zum Original < 3 (von 255);
  Phasenkorrelation verbessert das Ergebnis messbar.
* Erkennung: Rechteck-Kanten und Kreismitte/-radius jeweils auf ±1,5 mm.
* Entzerrung: synthetische Verzeichnung (k1 −0,25) wird um > 40 % reduziert.

Diese Zahlen sagen **nichts** über echte Bilder (Licht, Reflexe, Schatten, dunkles Material auf
dunklem Wabenbett, Unschärfe, Rolling Shutter). Echte Messungen fehlen.

Tests (alle offscreen, ohne Hardware): `test_scanprobe.py` (27), `test_scan_panel.py` (12),
`test_scan_marking.py` (7), `test_focus_export.py` (23), `test_focus_multi_region.py` (4),
`test_pi_calibration.py` (9, Fake-Pi), `test_pi_scan_endpoints.py` (22, Fake-Pi: Snapshot, moveto,
Jog-Rückfall, Z-Vorabprüfung, Anfrage-Zählung, Panel); Pi-seitig `tests/test_camera_calibration.py` (Repo-Wurzel).

## 3. Kalibrierung

Die Werte gehören zur Maschine und liegen auf dem Pi (Abschnitt 3a); `camera.json` hat
dasselbe Format und dient zum Import/Export. Der Ablauf Schritt für Schritt steht in
[KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md).

| Wert | Bedeutung | Ermitteln (Schritt in KAMERA_KALIBRIERUNG.md) | Stand |
|---|---|---|---|
| `image_width` / `image_height` | Aufnahmeauflösung | Schritt 1 | Platzhalter (640×480 eingebaut, 1280×720 im Beispiel) |
| `camera_matrix`, `dist_coeffs` | Linsenverzeichnung | Schritt 2 (Schachbrett, `cv2.calibrateCamera`) | nicht vorhanden (optional) |
| `scan_z` | feste Scanhöhe | Schritt 3 | Platzhalter 40 mm, Erreichbarkeit unbekannt |
| `flip_x`, `flip_y` | Spiegelung | Schritt 3 (Kopf joggen, Bildrichtung beobachten) | Platzhalter +1/+1 |
| `px_per_mm` | Maßstab auf dem Bett bei `scan_z` | Schritt 4 (Lineal/gelasertes Quadrat) | Platzhalter 4,0 (eingebaut) bzw. 5,12 (Beispiel) |
| `offset_mm` | Bildmitte relativ zum Laserpunkt | Schritt 5 (Fadenkreuz lasern) | Platzhalter (30, −20) bzw. (31,5, −18,2) |
| `rotation_deg` | Drehung Bild ↔ Achsen | Schritt 6 (gelaserte Linie) | Platzhalter 0 |
| `exposure` | feste Belichtung (treiberabhängig) | Schritt 7 | Platzhalter; Wertebereiche für DirectShow/V4L2 nur aus OpenCV-Doku, nicht geprüft |
| `crop_fraction` | Randbeschnitt gegen Vignettierung | Erfahrungswert | Standard 0,04 |
| `homography` | optional: 3×3 Bild → Bett (z. B. aus einer 4-Punkt-Messung) | – | wird gespeichert, vom Scan **noch nicht** genutzt |

**Alle Werte sind Platzhalter – gemessen ist nichts.** Im Simulationsmodus nutzt Studio die
eingebaute Platzhalter-Kalibrierung (`adapters.default_calibration()`).

Werkzeuge:

* **vorhanden:** `CameraCalibration` (Laden/Speichern/Prüfen per Python), Schachbrett-Skript als
  Codebeispiel in KAMERA_KALIBRIERUNG.md, Buttons „Vom Pi laden“, „Auf Pi speichern“,
  „Importieren …“, „Exportieren …“ im Scan-Panel.
* **offen:** Kalibrier-Assistent in Studio (Testbild, Fadenkreuz lasern, Versatz/Maßstab/Drehung
  per Klick messen, `camera.json` schreiben), Live-Vorschau, Einzelbild-Testaufnahme,
  Prüfmuster-Vergleich (< 0,5 mm) in der Oberfläche.

## 3a. Kalibrierung auf dem Pi speichern

Die Kalibrierung gehört zur **Maschine**, nicht zum Client: Studio auf dem PC, ein zweiter PC
oder später Tablet/Web lesen denselben Stand vom Pi.

**Ablageort** (erster Treffer gilt, `pi400/marlin/camera_calibration.py`):

1. `LUMACUT_CAMERA_CALIBRATION` (z. B. in `/etc/lumacut/lumacut.env`) – dann nur dieser Pfad
2. `/etc/lumacut/camera_calibration.json` (Standard; `install.sh` legt `/etc/lumacut` als
   `root:lumacut` mit Modus `1775` an, der Dienst darf dort schreiben: `ReadWritePaths=… -/etc/lumacut`)
3. `pi400/config/camera_calibration.json` im Repo (Entwicklung ohne `/etc`; per `.gitignore` nicht im Repo)
4. `$LUMACUT_DATA/camera_calibration.json` (`/var/lib/lumacut`; bei älteren Installationen,
   deren Dienst `/etc/lumacut` noch nicht schreiben darf)

Geschrieben wird an den ersten beschreibbaren Ort, **atomar** (temporäre Datei im selben
Verzeichnis, `fsync`, `rename`) – Leser sehen immer die alte oder die neue Datei. Fehlt die Datei,
liefert der Pi die Platzhalterwerte mit `"placeholder": true`; eine kaputte Datei ergibt ebenfalls
den Platzhalter plus `storage.error`. Studio verwendet einen Platzhalter **nie** für echte Scans.

**Datei / Schema** (`format` `lumacut-camera-calibration/1`, `schema_version` 1):

```json
{
  "format": "lumacut-camera-calibration/1",
  "schema_version": 1,
  "revision": 3,
  "updated_at": "2026-10-26T09:00:00Z",
  "updated_by": "LumaCut Studio (WERKSTATT-PC)",
  "calibrated": true,
  "notes": "Beispielwerte, nicht gemessen",
  "image_width": 1280, "image_height": 720,
  "px_per_mm": 5.12, "scan_z": 40.0,
  "offset_mm": [31.5, -18.2],
  "rotation_deg": 0.0, "flip_x": 1, "flip_y": 1,
  "crop_fraction": 0.04,
  "camera_matrix": null, "dist_coeffs": null,
  "exposure": null, "homography": null
}
```

Prüfung beim Speichern (deutsche Meldung, HTTP 400): `image_width` 160–8192 / `image_height`
120–8192 (ganzzahlig), `px_per_mm` 0,5–100, `scan_z` 0–90, `offset_mm` je ±200, `rotation_deg`
±180, `flip_x`/`flip_y` ±1, `crop_fraction` 0 bis < 0,4, `camera_matrix` 3×3 mit positiven
Brennweiten **zusammen mit** `dist_coeffs` (4/5/8/12/14 Werte), `homography` invertierbare 3×3,
`notes` ≤ 2000 / `updated_by` ≤ 80 Zeichen, unbekannte Felder werden abgelehnt.
`revision` und `updated_at` setzt der Pi.

**API** (`pi400/marlin/camera_calibration.py`, in `web.py` registriert):

| Methode | Pfad | Verhalten |
|---|---|---|
| GET | `/api/camera/calibration` | Datensatz wie oben plus `placeholder`, `status` (`platzhalter`/`unkalibriert`/`kalibriert`) und `storage` (`path`, `write_path`, `writable`, `error`) |
| PUT | `/api/camera/calibration` | Body JSON mit allen Werten und der zuletzt gelesenen `revision`. 200 → neuer Datensatz (`revision` + 1, `message`). 409 → inzwischen von anderem Client geändert, Antwort enthält `current`. 400 Prüffehler, 415 kein `application/json`, 403 fremder `Origin`, 413 > 64 KB |

Der Pi prüft wie bisher **keinen Schlüssel** (siehe MACHINE_API.md). Gegen Schreiben von
fremden Webseiten (CSRF) akzeptiert PUT nur `application/json` und lehnt einen fremden
`Origin` ab.

**Studio:**

* Modus „Maschine“: beim Umschalten (wenn verbunden) und spätestens beim Scan holt Studio die
  Kalibrierung vom Pi; das Label zeigt Status, Revision, Zeitpunkt und Werte. „Vom Pi laden“
  liest neu.
* „Importieren …“ lädt eine `camera.json`; im Pi-Modus fragt Studio danach, ob sie auf dem Pi
  gespeichert werden soll. „Auf Pi speichern“ (mit Bestätigung) schreibt per PUT mit Revision.
  Bei 409 bleiben die lokalen Werte erhalten, Studio meldet den neuen Stand auf dem Pi; ein
  zweiter Klick speichert gegen die neue Revision.
* `calibrated` setzt Studio auf `true`, sobald die Werte von den eingebauten Platzhaltern abweichen.
* Alter Pi ohne Endpunkt (404/405): „Pi-Software zu alt – Kalibrierung wird nicht auf dem Pi
  gespeichert …“; Studio nutzt dann eine importierte `camera.json` wie früher. Pi nicht
  erreichbar: „Pi nicht erreichbar – Kalibrierung laden/speichern nicht möglich …“.
* Simulation: kein Zugriff auf den Pi, eingebaute oder importierte Kalibrierung.

**Umzug einer vorhandenen `camera.json`:** Pi aktualisieren, in Studio Modus „Maschine“,
verbinden, „Importieren …“ → `camera.json` wählen → „Auf Pi speichern“ bestätigen. Ohne Studio:
`curl http://lumacut.local:8080/api/camera/calibration` lesen, Werte plus `"revision": <gelesen>`
per `curl -X PUT -H 'Content-Type: application/json' --data @neu.json …` schreiben.
Bestehende Installationen: `pi400/update.sh` kopiert die Dienstdatei nicht; bis
`install.sh`-Schritte (Rechte für `/etc/lumacut`, Dienstdatei) nachgezogen sind, speichert der Pi
unter `/var/lib/lumacut/camera_calibration.json` (`storage.path` zeigt den Ort).

## 4. Offene Punkte für die Integration in Studio

| Punkt | Status |
|---|---|
| Kameramodell, Objektiv und Anschluss festlegen | **offen** (unbekannt) |
| Echte Kalibrierung messen (alle Werte aus Abschnitt 3) und auf dem Pi speichern | **offen** |
| Kalibrierung auf dem Pi speichern (Datei, GET/PUT, Revision, Studio-Anbindung) | **erledigt** (26.10., Abschnitt 3a); auf dem echten Pi **ungeprüft** |
| Kamera-Endpunkt auf dem Pi (Snapshot) | **erledigt** in Studio (26.10., „Pi (Snapshot)", Fake-Pi-Tests); mit echter Kamera **ungeprüft**; Belichtung am Pi nicht einstellbar |
| Absolutes Verfahren auf dem Pi | **erledigt** für XY (`op=moveto`, Jog-Rückfall für alte Pis); Z weiter Jog-Schritte; auf der Maschine **ungeprüft**, Zeitgewinn nicht gemessen |
| Scan im Pi-Modus ohne vorheriges G30 (Z-Sperre des Pi) | **erledigt** – Vorabprüfung vor dem Start mit Hinweis auf „Fokus (G30)" |
| Scanhöhe unter der Pi-Rückzugshöhe (`z_clearance_mm`, Standard 20) | moveto würde Z je Kachel anheben → Studio fährt dann in Jog-Schritten (langsam, Hinweis); Scanhöhe ≥ Rückzugshöhe kalibrieren |
| `scan_z` im Z-Hub erreichbar | **ungeprüft** |
| Kachel-Scan, Stitching, Erkennung | **erledigt** (Code + synthetische Tests), mit echten Bildern **ungeprüft** |
| Entzerrung (Linsenmodell) | **erledigt** (synthetisch), echte Kamera **ungeprüft** |
| Leerbett-Referenz für die Erkennung | API vorhanden (`detect_objects(..., background=...)`), **offen** in der Oberfläche (kein Button zum Aufnehmen/Speichern) |
| Mosaik als Canvas-Hintergrund, Design und Werkstück-Umrisse darüber | **erledigt** |
| Live-Vorschau / Einzelbild der Kamera in Studio | **offen** |
| Kalibrier-Assistent | **offen** |
| Schritt „Markieren“ im Ablauf (Werkstücke antippen, Bereich aufziehen, Auswahl als Bereich) | **erledigt** (26.10., `test_scan_marking.py`) |
| Fokuskorrektur über mehrere Werkstückhöhen inkl. Fokus-Absenkung/3D | **erledigt** (`test_focus_multi_region.py`); Studio blockiert, wenn die Pi-Sperre (letztes G30 + 2 mm) greifen würde |
| Pi-Oberfläche nach Auto-Probe | **offen/Hinweis:** jeder Taster-Punkt setzt die Pi-Oberfläche neu; nach dem Proben gilt der zuletzt gemessene Punkt. Vor dem Auftrag G30 auf dem niedrigsten Werkstück. |
| Windows-Build (PyInstaller) mit OpenCV | **ungeprüft** – `build-windows.bat` verlässt sich auf die OpenCV-Hooks; Kamera-Backend DirectShow/MSMF nie getestet |
| Belichtung/Weißabgleich/Fokus fest stellen | **ungeprüft** – nur Belichtung wird gesetzt; Weißabgleich und Fokus muss die Kamera selbst fest halten |
| Gesamtablauf an der echten Maschine | **ungeprüft** |
