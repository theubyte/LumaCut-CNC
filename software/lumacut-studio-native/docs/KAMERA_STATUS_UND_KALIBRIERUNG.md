# Kamera am Laserkopf: Ist-Stand und Kalibrierung

Stand: 26.10.2026, Branch `main` (geprüft gegen Code und Doku im Repo, nicht an der Maschine).
Zurück zur Übersicht: [SCAN_PROBE.md](SCAN_PROBE.md) · Kalibrierablauf: [KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md)

**Kurzfassung:** Die Kamera-Software (Kachel-Scan, Stitching, Objekterkennung, Kalibriermodell,
Studio-Oberfläche) ist implementiert und mit **synthetischen Bildern** getestet. Mit einer
echten Kamera ist bisher **nichts** gelaufen: Kameramodell und Anschluss sind unbekannt, alle
Kalibrierwerte sind Platzhalter, und der Pi hat weder einen Kamera-Endpunkt noch einen
absoluten Fahrbefehl.

Legende: **erledigt** = im Code vorhanden und automatisch getestet · **offen** = fehlt ·
**ungeprüft** = vorhanden, aber nie mit echter Hardware/auf dem Zielsystem gelaufen.

## 1. Wie die Kamera heute angebunden ist

| Teil | Stand | Quelle |
|---|---|---|
| Kamera-Zugriff in Studio | `OpenCvCamera`: `cv2.VideoCapture(Quelle)`; Quelle = USB-Index (`0`) oder Stream-URL. Setzt Auflösung und (optional) feste Belichtung aus `camera.json`, verwirft vor jeder Aufnahme 2 gepufferte Bilder. **ungeprüft** – nie mit echter Kamera gelaufen. | `src/scanprobe/adapters.py` |
| Wo die Kamera hängt | Die Kamera wird **von Studio (PC/Tablet) direkt** geöffnet, nicht über den Pi. Eine Stream-URL wie `http://lumacut.local:8081/stream` steht nur als Beispiel im Tooltip – auf dem Pi läuft **kein** solcher Dienst. | `panel.py`, `adapters.py` |
| Kamera auf dem Pi | **offen.** `pi400/` enthält keinen Kamera-Code (kein Aufnahme-, Stream- oder Snapshot-Endpunkt). Die Pi-API kennt nur `home, jog, probe, park, frame, start, abort, estop, estop_reset, connect, autorun`. `docs/ENTWICKLUNG.md` nennt „Kamera auf dem Pi (Aufnahme, Kachel-Scan, Zusammensetzen) fehlt“. Die Dienstdatei hat die Gruppe `video`, genutzt wird sie nicht. | `pi400/marlin/web.py`, `lumacut-marlin.service` |
| Kopfbewegung für den Scan | `PiMachine.move_to` zerlegt jede Fahrt in die erlaubten Jog-Schritte ±10/±1/±0,1 mm (ein HTTP-Aufruf je Schritt, Pi wartet mit `M400`). Funktioniert ohne Pi-Änderung, ist aber langsam. Ein `op=move` fehlt. **ungeprüft** auf der Maschine. | `adapters.py`, `web.py` (`op == "jog"`) |
| Z auf Scanhöhe | Der Scan fährt zuerst Z auf `scan_z` (Platzhalter 40 mm). Laut Pi-Code wird **jede** Z-Fahrt (auch Jog) abgelehnt, solange keine Werkstückoberfläche gemessen ist („Keine Werkstückhöhe bekannt …“). Im Pi-Modus muss also vor dem Scan ein G30/„Fokus“ gelaufen sein. Ob `scan_z` = 40 mm im Z-Hub erreichbar ist, ist **unbekannt**. | `pi400/marlin/transport.py` (`_z_move_guard_locked`) |
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
| `panel.py` | Scan-Panel in Studio: Modus Simulation/Pi, Kamera-Quelle, `camera.json` laden, Scan, Mosaik als Canvas-Hintergrund, erkannte Werkstücke als Liste und Overlay, Markieren (seit 26.10.), Auto-Probe, Heatmap. | – |

**Genauigkeit – nur synthetisch geprüft** (`tests/test_scanprobe.py`, Fake-Kamera, Kalibrierung
640×480, 4 px/mm, 1,5° Drehung, Positionsfehler bis 0,4 mm):

* Mosaik deckt > 97 % der Fläche, mittlere Grauwertabweichung zum Original < 3 (von 255);
  Phasenkorrelation verbessert das Ergebnis messbar.
* Erkennung: Rechteck-Kanten und Kreismitte/-radius jeweils auf ±1,5 mm.
* Entzerrung: synthetische Verzeichnung (k1 −0,25) wird um > 40 % reduziert.

Diese Zahlen sagen **nichts** über echte Bilder (Licht, Reflexe, Schatten, dunkles Material auf
dunklem Wabenbett, Unschärfe, Rolling Shutter). Echte Messungen fehlen.

Tests (alle offscreen, ohne Hardware): `test_scanprobe.py` (27), `test_scan_panel.py` (12),
`test_scan_marking.py` (7), `test_focus_export.py` (23), `test_focus_multi_region.py` (4).

## 3. Kalibrierung

Alle Werte stehen in `camera.json`; der Ablauf Schritt für Schritt steht in
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

**Alle Werte sind Platzhalter – gemessen ist nichts.** Im Simulationsmodus nutzt Studio die
eingebaute Platzhalter-Kalibrierung (`adapters.default_calibration()`).

Werkzeuge:

* **vorhanden:** `CameraCalibration` (Laden/Speichern/Prüfen per Python), Schachbrett-Skript als
  Codebeispiel in KAMERA_KALIBRIERUNG.md, Button „Laden …“ im Scan-Panel.
* **offen:** Kalibrier-Assistent in Studio (Testbild, Fadenkreuz lasern, Versatz/Maßstab/Drehung
  per Klick messen, `camera.json` schreiben), Live-Vorschau, Einzelbild-Testaufnahme,
  Prüfmuster-Vergleich (< 0,5 mm) in der Oberfläche.

## 4. Offene Punkte für die Integration in Studio

| Punkt | Status |
|---|---|
| Kameramodell, Objektiv und Anschluss festlegen | **offen** (unbekannt) |
| Echte `camera.json` messen (alle Werte aus Abschnitt 3) | **offen** |
| Kamera-Endpunkt auf dem Pi (Snapshot/Stream) oder Kamera direkt am PC | **offen** – Studio kann beides öffnen (USB-Index/URL), der Pi liefert nichts |
| Absolutes Verfahren `op=move` auf dem Pi | **offen** – Übergang: Jog-Schritte (langsam) |
| Scan im Pi-Modus ohne vorheriges G30 (Z-Sperre des Pi) | **offen** – laut Pi-Code wird die Z-Fahrt auf `scan_z` sonst abgelehnt; Studio meldet das noch nicht vorab |
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
