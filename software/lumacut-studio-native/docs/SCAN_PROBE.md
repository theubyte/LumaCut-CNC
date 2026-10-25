# Kamera-Scan, Objekterkennung und Mehrbereichs-Proben (`src/scanprobe/`)

Ziel: deutlich besser als xTool – kein einzelner verzerrter Snapshot, sondern ein
scharfes, vermessenes Bettbild aus vielen Kacheln, automatisch erkannte Werkstücke
und **nur dort** ein eigenes Höhenmesh pro Werkstück mit adaptiver Fokuskorrektur.

Der Kern ist Qt-frei (numpy + OpenCV) und läuft in Studio wie auf dem Pi.
Nur `qt_bridge.py` importiert PySide6.

## Ablauf

1. **Kachel-Scan** (`plan_tiles`, `TileScanner`)
   * Der Kopf fährt zuerst **nur Z** auf die feste Scanhöhe (`calibration.scan_z`)
     und dann schlangenförmig (Serpentine) mit Überlappung (Standard 25 %).
   * Pro Kachel: `wait_idle` → Ausschwingzeit → Bild → Entzerrung (OpenCV-Linsenmodell).
   * Kopfpositionen werden auf den Fahrbereich geklemmt (Kameraversatz). Nicht
     erreichbare Randstreifen stehen in `plan.uncovered` und `plan.warnings`.
2. **Stitching** (`stitch_mosaic`)
   * Jede Kachel wird über die bekannte Position (Affinmatrix aus px/mm, Drehung und
     Spiegelung) ins Maschinen-mm-Raster gelegt.
   * Phasenkorrelation gegen das bisherige Mosaik korrigiert Positionsfehler bis
     ±1,5 mm. Bei strukturlosen Flächen bleibt die bekannte Position stehen.
   * Belichtungsangleich, mittengewichtetes Überblenden → keine Nähte.
   * Ergebnis `Mosaic`: Bild + `mm_per_px` + `origin_mm` (Zeile 0 = kleinstes Y).
     `save()` schreibt PNG und JSON (`lumacut-scan-mosaic/1`).
3. **Objekterkennung** (`detect_objects`)
   * Vordergrund über eine Leerbett-Referenz (falls vorhanden), sonst Farbabstand
     zum Bettmedian.
   * Klassifiziert Kreis, Rechteck (auch gedreht) und Polygon.
   * Liefert `DetectedObject` (Polygon, Bounds, Mitte, Radius bzw. Größe, Drehung, Konfidenz).
4. **Bereiche** (`areas_from_objects`, `areas_from_design_bounds`)
   * Ohne Design: alle erkannten Objekte.
   * Mit Design-Bounding-Boxen aus dem Canvas: nur Objekte unter dem Design. Liegt
     Design außerhalb jedes Objekts, wird die Design-Box selbst zum Bereich (mit Hinweis).
   * Manuelle Bereiche: `ProbeArea.from_rect(...)` bzw. `ProbeArea(id, Polygon, ...)`.
5. **Proben** (`plan_probe_job`, `ProbeRunner`)
   * Raster je Bereich (Abstand, Randabstand), nur Punkte innerhalb der Form.
   * Punkte, bei denen der Kopf wegen des Tasterversatzes (X −23 / Y +15) den
     Fahrbereich verlassen würde, werden übersprungen.
   * Reihenfolge: Bereiche nach nächstem Nachbarn, innerhalb Serpentine (beste von 8 Varianten).
   * Fehlmessung → Wiederholung leicht versetzt (innerhalb der Form). Bleibt sie
     erfolglos, wird interpoliert und markiert (`FAILED`).
   * Ausreißer (Span, Staub) gegen den Nachbar-Median → nachmessen. Reproduzierbar = echte Stufe.
   * **Adaptiv**: Zellmitten werden gegen die bikubische Vorhersage geprüft;
     gekrümmte Zellen werden auf halben Abstand verfeinert.
6. **Höhenmesh** (`HeightMap`, `HeightMapSet`)
   * Ein Mesh pro Bereich, zusammen in einem Set. Abfragen bilinear, bikubisch oder nächster Knoten.
   * `stats()`: Neigung in mm/100 mm, Ebenheit, Fehlpunkte.
   * JSON (`lumacut-heightmaps/1`) mit Bild-Fingerabdruck je Bereich.
7. **Fokuskorrektur** (`apply_focus_compensation`)
   * `Z = Oberfläche + 7 − 1,5` pro Segment (≤ 2 mm). Nie unter Oberfläche + 2 mm.
   * G0: erst hoch, dann fahren; absenken erst am Ziel.
   * Z max. 9 mm/s → Vorschub wird bei steilen Stücken begrenzt (gemeldet).
   * `S` wird nur wiederholt, wenn die Originalzeile `S` hatte (Inline-Laser-Modus `M3 I`).
   * Nach G0 wird `F` beim nächsten G1 neu gesetzt (der Pi setzt bei G0 ggf. F9000).
   * Bögen (G2/G3) und eigene Z-Wörter werden abgelehnt.
8. **Vorschau** `render_heatmap(maps, "heat.png", mosaic=mosaic)`: TURBO-Farbskala über
   dem Scanbild, Messpunkte, Fehlpunkte (rot), Legende.
9. **Wiederverwendung** `ScanProbeWorkflow.try_reuse(saved, mosaic)`
   * Bildvergleich je Bereich (Versatz ≤ 0,5 mm, Ähnlichkeit ≥ 0,85).
   * Dazu 3 Kontrollmessungen pro Bereich statt kompletter Abtastung.

## Bedienung / Steuerung

`RunControl` erlaubt `pause()`, `resume()` und `cancel()` (wirft `Cancelled` am
nächsten sicheren Punkt) und liefert `Progress(phase, done, total, message, eta_s)`.
`ScanProbeWorkflow.estimate()` gibt die Dauer vor dem Start an.

```python
from scanprobe import *
wf = ScanProbeWorkflow(machine, camera, probe, CameraCalibration.load("camera.json"),
                       ProbeSettings(spacing_mm=15), RunControl(on_progress=print))
print(wf.estimate())
res = wf.run(design_bounds=[Rect(80, 80, 140, 120)])
res.mosaic.save("scan.png"); res.maps.save("hoehen.json")
render_heatmap(res.maps, "heat.png", mosaic=res.mosaic)
gcode_z, report = apply_focus_compensation(gcode, res.maps)
```

Qt: `scanprobe.qt_bridge.ScanProbeWorker(workflow, design_bounds=...)` als QThread mit
Signalen `progress`, `tile_captured`, `finished_ok`, `cancelled`, `failed`.

## Bedienung in LumaCut Studio (Scan-Panel)

Rechte Spalte, Gruppe **„Scan & Probe"** (`src/scanprobe/panel.py`, eingebunden in `main.py`):

1. **Modus** wählen: „Simulation (ohne Hardware)" (eingebautes Testbett, keine Hardware – zum Ausprobieren
   und für Tests) oder „Maschine (Pi-API + Kamera)" (nutzt die Verbindung aus dem Maschinen-Panel).
2. Nur Pi-Modus: **Kamera-Quelle** (USB-Index `0` oder Stream-URL) eintragen und
   bei „Kalibrierung" **„Laden …"** → `camera.json`, siehe
   **[KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md)** (Werte, Format, Ablauf).
3. **„Scan starten"**: Kachel-Scan + Objekterkennung. Das Mosaik wird Canvas-Hintergrund,
   erkannte Objekte erscheinen in der Liste und als gestrichelte Hilfsformen auf dem Canvas
   (nicht Teil des Dokuments, nicht anwählbar).
4. Objekte in der Liste an-/abhaken, **Rasterabstand** einstellen, optional
   **„Nur Werkstücke unter dem Design proben"** (Standard; Bereiche aus den Bounding-Boxen
   der sichtbaren Designformen ∩ erkannte Werkstücke – ohne Scan direkt aus dem Design).
5. **„Auto-Probe"**: probt nur die angehakten Objekte bzw. Designbereiche. Danach liegt die
   Höhen-Heatmap halbtransparent über dem Canvas, Min/Max-Z wird angezeigt.
6. **„Scan + Probe (komplett)"**: beides in einem Lauf; mit „Geladenes Mesh nach
   Kontrollmessung wiederverwenden" werden passende Bereiche nur per Bildvergleich + 3 Kontrollpunkten geprüft.
7. Während des Laufs: Fortschritt, Phase und Restzeit; **Pause/Fortsetzen** und
   **Abbrechen** (an sicheren Punkten, `RunControl`). Vor echten Läufen fragt Studio nach.
8. Anzeige-Schalter Scanbild/Werkstück-Umrisse/Höhenkarte, **„Höhenmesh speichern …"/„Laden …"** (`hoehen.json`),
   **„Scan-Anzeige leeren"**.

Hardware-Anbindung (`src/scanprobe/adapters.py`, Qt-frei):

* `PiMachine` – `move_to` über die Pi-API. Da der Pi **keinen absoluten Fahrbefehl**
  hat, wird mit erlaubten Jog-Schritten (10/1/0,1 mm) gefahren: langsam (ein HTTP-Aufruf
  je Schritt), aber sicher; Z wird nie unter Oberfläche + 2 mm geschickt, Z nach unten
  wird abgerundet. Vorher: verbunden, gehomt, kein Not-Aus, kein Job aktiv.
* `PiProbe` – `op=probe` an (x, y) des Laserpunkts; Z wird aus der Antwort gelesen.
* `OpenCvCamera` – `cv2.VideoCapture` (USB/URL), feste Auflösung/Belichtung aus
  `camera.json`, verwirft gepufferte Bilder vor jeder Aufnahme.
* `simulated_setup()` – Fake-Maschine/Kamera/Taster mit zwei Werkstücken.

## Schnittstellen für die anderen Teile

| Teil | Erwartung |
|---|---|
| Maschine (Pi-API) | `MachineInterface.move_to(x\|None, y\|None, z=None, feed=None)`, `wait_idle()` |
| Taster | `ProbeInterface.probe_z(x, y, *, safe_z, feed, max_depth) -> float \| None` – x/y = **Laserpunkt**, der Pi rechnet den Tasterversatz selbst |
| Kamera | `CameraInterface.capture() -> np.ndarray` (BGR) |
| Canvas | Mosaik-PNG + `metadata()` (mm/px, Ursprung, Affinmatrix) als Hintergrund; `DetectedObject.to_dict()` als Hilfsformen; Design-Bounding-Boxen → `design_bounds`; Heatmap-PNG als Overlay |

Kalibrierung `camera.json` (`lumacut-camera-calibration/1`): `px_per_mm` auf
Scanhöhe, `offset_mm` (Bildmitte relativ zum Laserpunkt), `rotation_deg`, Spiegelung,
optional `camera_matrix`/`dist_coeffs` aus `cv2.calibrateCamera`, `exposure`.
Details, Beispiel und Kalibrierablauf: [KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md).

## Offene Punkte (Hardware)

* Kameramodell und Anschluss (USB oder CSI am Pi), Auflösung, Belichtung fest/auto.
* Echte Kalibrierwerte (px/mm auf Scanhöhe, Versatz zum Laser, Verzeichnung).
* Pi-Probe-API: Laut Doku hebt der Pi nach G30 auf max(20, Oberfläche+2). Der
  niedrige Zwischenhub (`hop_mm`) wirkt erst, wenn der Pi `safe_z` übernimmt.
* Fokuskorrektur soll langfristig auf dem Pi laufen. Die Funktion ist dafür Qt-frei.
  Aus der Oberfläche wird kompensierter G-Code noch nicht gesendet
  (`apply_focus_compensation` ist vorhanden, Header: eine G/M-Anweisung pro Zeile).
* Pi-API ohne absolutes Verfahren und ohne Kamera-Endpunkt → Jog-basierte Bewegung
  (langsam). Ein `op=move`/Kamera-Endpunkt auf dem Pi würde den Scan stark beschleunigen.
* Der Pi erlaubt Z-Bewegungen nur relativ zu *einer* gemessenen Oberfläche; bei mehreren
  unterschiedlich hohen Werkstücken gilt die zuletzt gemessene.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_scanprobe.py tests/test_scan_panel.py
```

Alle Tests laufen mit Fakes (`scanprobe.fakes`: synthetisches Bett, Maschine mit
Positionsfehlern und Tasterausfällen, Kamera mit optionaler Linsenverzeichnung).
