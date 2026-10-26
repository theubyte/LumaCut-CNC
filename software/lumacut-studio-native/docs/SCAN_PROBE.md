# Kamera-Scan, Objekterkennung und Mehrbereichs-Proben (`src/scanprobe/`)

Ziel: deutlich besser als xTool – kein einzelner verzerrter Snapshot, sondern ein
scharfes, vermessenes Bettbild aus vielen Kacheln, automatisch erkannte Werkstücke
und **nur dort** ein eigenes Höhenmesh pro Werkstück mit adaptiver Fokuskorrektur.

Der Kern ist Qt-frei (numpy + OpenCV) und läuft in Studio wie auf dem Pi.
Nur `qt_bridge.py` importiert PySide6.

**Ist-Stand Kamera und Kalibrierung** (was echt läuft, was nur simuliert ist, was offen ist):
[KAMERA_STATUS_UND_KALIBRIERUNG.md](KAMERA_STATUS_UND_KALIBRIERUNG.md).

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
2. Nur Pi-Modus: **Kamera** wählen – „Pi (Snapshot)" (Kopfkamera am Pi über
   `GET /api/camera/snapshot`; Standard, sobald der Pi Snapshot und Kamera meldet) oder
   „Lokal (USB/URL)" (USB-Index `0` oder Stream-URL eintragen) – und
   bei „Kalibrierung" den Stand vom Pi prüfen (wird automatisch geholt; sonst **„Importieren …"** →
   `camera.json` und **„Auf Pi speichern"**), siehe
   **[KAMERA_KALIBRIERUNG.md](KAMERA_KALIBRIERUNG.md)** (Werte, Format, Ablauf).
3. **„Scan starten"**: Kachel-Scan + Objekterkennung. Das Mosaik wird Canvas-Hintergrund,
   erkannte Objekte erscheinen in der Liste und als gestrichelte Hilfsformen auf dem Canvas
   (nicht Teil des Dokuments, nicht anwählbar).
4. Objekte in der Liste an-/abhaken, **Rasterabstand** einstellen, optional
   **„Nur Werkstücke unter dem Design proben"** (Standard; Bereiche aus den Bounding-Boxen
   der sichtbaren Designformen ∩ erkannte Werkstücke – ohne Scan direkt aus dem Design).
   **Markieren** (Ablauf-Schritt „Markieren" oder **„Auf Canvas markieren"**): ein Klick/kurzes Antippen
   auf ein erkanntes Werkstück hakt es an/ab (angehakt = gefüllt); ein aufgezogener Bereich hakt die
   darin liegenden Werkstücke an oder wird – ohne Werkstück darin – zum **manuellen Bereich**
   (orange gestrichelt, auf die Arbeitsfläche beschnitten). **„Auswahl als Bereich"** macht aus den
   gewählten Designformen (Umriss + 3 mm) Bereiche; **„Manuelle Bereiche löschen"** setzt zurück.
   Manuelle Bereiche werden auch ohne Scan geprobt.
5. **„Auto-Probe"**: probt nur die angehakten Objekte bzw. Designbereiche. Danach liegt die
   Höhen-Heatmap halbtransparent über dem Canvas, Min/Max-Z wird angezeigt.
6. **„Scan + Probe (komplett)"**: beides in einem Lauf; mit „Geladenes Mesh nach
   Kontrollmessung wiederverwenden" werden passende Bereiche nur per Bildvergleich + 3 Kontrollpunkten geprüft.
7. Während des Laufs: Fortschritt, Phase und Restzeit; **Pause/Fortsetzen** und
   **Abbrechen** (an sicheren Punkten, `RunControl`). Vor echten Läufen fragt Studio nach.
8. Anzeige-Schalter Scanbild/Werkstück-Umrisse/Höhenkarte, **„Höhenmesh speichern …"/„Laden …"** (`hoehen.json`),
   **„Scan-Anzeige leeren"**.

Hardware-Anbindung (`src/scanprobe/adapters.py`, Qt-frei):

* `PiMachine` – `move_to` über die Pi-API. XY per `op=moveto` (absolut, ein HTTP-Aufruf je
  Kachel, Pi antwortet nach `M400` mit der Position; Studio prüft sie auf ±0,2 mm). Z hat auf
  dem Pi keinen absoluten Befehl und läuft weiter in Jog-Schritten (10/1/0,1 mm): nie unter
  Oberfläche + 2 mm, abwärts abgerundet, aufwärts vor XY. `wait_idle` fragt `/api/status`
  ab, bis `busy` aus und der Zustand `Idle` ist. Alter Pi (kein `camera` im Status oder
  „Unbekannte Marlin-Aktion: moveto") → Rückfall auf Jog-Schritte für XY mit Hinweis im Panel.
  Vor dem Scan prüft `check_scan_height`: verbunden, gehomt, kein Not-Aus/Job, Scanhöhe im
  Z-Fahrbereich, Oberfläche per „Fokus (G30)" gemessen (sonst lehnt der Pi die Z-Fahrt ab),
  Scanhöhe ≥ Oberfläche + 2 mm. Liegt die Scanhöhe unter der Rückzugshöhe des Pi
  (`z_clearance_mm`, Standard 20), würde moveto den Kopf bei jeder Kachel anheben – dann
  fährt der Scan in Jog-Schritten (Hinweis im Panel).
* `PiProbe` – `op=probe` an (x, y) des Laserpunkts; Z wird aus der Antwort gelesen.
* `PiSnapshotCamera` – `GET /api/camera/snapshot?w=&h=` mit der Bildgröße aus der
  Kalibrierung, JPEG → BGR. 503/Netzfehler/kaputtes JPEG: 2 Wiederholungen; 404 (alter Pi)
  und falsche Bildgröße: sofort deutsche Fehlermeldung. Der Pi verwirft selbst die ersten
  5 Bilder (Belichtung), setzt aber **keine** Belichtung aus der Kalibrierung.
* `OpenCvCamera` – `cv2.VideoCapture` (USB/URL), feste Auflösung/Belichtung aus
  `camera.json`, verwirft gepufferte Bilder vor jeder Aufnahme.
* Versatz, Drehung, Spiegelung und Entzerrung kommen bei beiden Kameras gleich aus der
  Kalibrierung vom Pi (`TileScanner`/`stitch_mosaic`); getestet: gleiches Bild → gleiches Mosaik.
* `simulated_setup()` – Fake-Maschine/Kamera/Taster mit zwei Werkstücken.

## Fokuskorrektur beim Export (Höhenmesh)

Checkbox **„Fokuskorrektur anwenden (Höhenmesh)"** im Scan-Panel (Standard: aus).
Ohne Höhenmesh (nach „Auto-Probe" oder „Höhenmesh laden …") ist sie deaktiviert und ein
Hinweis wird angezeigt. Ist sie aus, bleiben **„An Pi senden"** und der normale Export
**unverändert**.

Ist sie an, wird der normale Marlin-G-Code des Canvas (`document_to_gcode`) per
`scanprobe.focus_export.compensate_for_export` → `apply_focus_compensation` umgerechnet:

* **„An Pi senden"** (`main.py`, `_send_canvas_job`) schickt den korrigierten G-Code.
* **„G-Code exportieren …"** im Scan-Panel speichert ihn als Datei (mit Korrektur, wenn angehakt,
  sonst unverändert) – aus derselben Auftragsquelle wie „An Pi senden" (`window().job_tools.job_gcode()`:
  Schnittplaner, **„Nur Auswahl"** und Planer-Hinweise wie weggelassene Anfahrten; ohne JobTools
  `lumacut_job.planner.optimized_document_gcode`). Datei und gesendeter Auftrag sind also identisch,
  auch bei „Nur Auswahl" (ohne Auswahl bricht der Export mit Meldung ab). Eine eigene Quelle lässt
  sich über `ScanPanel.job_gcode_source` setzen.
* Z je Segment = Oberfläche (bilinear aus dem Mesh) + 5,5 mm (Fokus 7,0 − Tasterumschaltung 1,5);
  lange Linien werden in ≤ 2 mm-Stücke geteilt. Die erste Brennbewegung bekommt ein explizites Z.
* **Fokus-Absenkung je Durchgang** (`z_step` der Ebene, auch Schichten-Relief aus
  `lumacut_materials`): die relativen Blöcke `G91` / `G0 Z-… F600` / `G90` werden nicht
  ausgegeben, sondern als Versatz auf das Mesh-Z gerechnet (Durchgang 2 = Mesh-Z − z_step usw.,
  nach der Ebene wieder Fokushöhe). Der Versatz darf nie unter Oberfläche + 2 mm führen
  (bei Fokus 5,5 mm also max. 3,5 mm; das Canvas begrenzt ohnehin auf 3 mm) – sonst Fehler.
* Leistung (S) und Vorschub (F) je Ebene, Reihenfolge aus dem Schnittplaner, Materialtest-Raster
  und Schraffuren bleiben unverändert; nur Z kommt hinzu, Linien werden geteilt.

Prüfungen (deutsche Meldungen; **Fehler** blockieren, **Warnungen** müssen bestätigt werden):

| Fall | Verhalten |
|---|---|
| G2/G3-Bögen im G-Code | Fehler – Bögen vorher in Liniensegmente auflösen (Canvas-Export erzeugt nur Linien). |
| Absolute Z-Wörter oder Z zusammen mit X/Y im G-Code | Fehler – entfernen oder ohne Korrektur exportieren. (Relative Fokus-Absenkung je Durchgang ist erlaubt, s. o.) |
| Fokus-Absenkung würde unter Oberfläche + 2 mm führen | Fehler. |
| Kein Höhenmesh / keine Brennstrecke im Mesh | Fehler. |
| Teile des Jobs außerhalb der geprobten Bereiche | Warnung mit Länge in mm und Beispielpunkt. **Fallback:** dort gilt die *höchste gemessene Oberfläche* (Fokus eher zu hoch, nie zu tief / keine Kollision). |
| Bild-Fingerabdruck passt nicht zum aktuellen Scan (Material bewegt) | Fehler – neu proben. |
| Kein aktueller Scan / Mesh ohne Fingerabdruck | Warnung (Lage nicht prüfbar). |
| Mesh älter als 8 h oder ohne Zeitstempel | Warnung. |
| Ziel-Z unter Pi-Oberfläche + 2 mm (z. B. mehrere Werkstücke unterschiedlicher Höhe, G30 auf dem höheren) | Fehler – der Pi würde den Auftrag mitten im Lauf abbrechen. G30 auf dem niedrigsten Werkstück oder Fokus-Absenkung verringern. |

Grenzen:

* Nur G-Code in mm mit absoluten X/Y (G21/G90); keine Bögen, keine absoluten Z-Werte. Erlaubt ist
  nur die relative Fokus-Absenkung je Durchgang.
* Der Relief-Export im Material-Dialog (`lumacut_materials`) sendet/speichert selbst und nutzt die
  Checkbox (noch) nicht. Die Kernfunktion kann Relief-G-Code korrigieren (getestet); die
  UI-Anbindung dort steht aus. Der optionale Tiefen-Hook (`gcode.pass_hook`) ist in Studio aus;
  Hook-Zeilen mit eigenem Z würden abgelehnt.
* Der Pi fokussiert vor der ersten Brennbewegung auf *seine* gemessene Oberfläche und prüft Z
  nur gegen diese eine Oberfläche (≥ Oberfläche + 2 mm).
  Mehrere Werkstücke: Z wird je Punkt aus dem passenden Mesh gerechnet (inkl. `z_step` und 3D-Tiefe,
  getestet in `test_focus_multi_region.py`); Studio blockiert, wenn das niedrigste Ziel-Z unter
  dieser Pi-Sperre läge.
* Der Pi hängt an jede Bewegung mit Z ein `M400`/`M114` an. Bei der Korrektur hat fast jedes
  Segment Z → der Planer läuft leer, der Laser **stockt** (Punkte/Brandflecken an Segmentgrenzen
  möglich). Empfehlung: Pi-seitig Z-Prüfung ohne `M400` für Folgezeilen. Bis dahin vorsichtig mit
  niedriger Leistung testen.
* Noch nicht auf echter Hardware getestet.

Canvas-Overlays (Scanbild, Werkstück-Umrisse, Heatmap) liegen auf Z 5·10⁸ – über allen Ebenen
(Ebenen nutzen Rang × 10⁶, ein 5×5-Materialtest hat schon 26 Ebenen), aber unter Auswahlrahmen
und Gummiband. Sie sind nicht anklickbar, nicht Teil des Dokuments und erzeugen keine Undo-Einträge.

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
* Fokuskorrektur soll langfristig auf dem Pi laufen (Funktion ist dafür Qt-frei). Derzeit
  rechnet Studio den G-Code um, siehe „Fokuskorrektur beim Export".
* Scan über `op=moveto` + Snapshot ist nur gegen einen Fake-Pi getestet. Rechnerisch
  (Standardplan, 12 Kacheln, `test_pi_scan_endpoints.py`): 49 Pi-Anfragen statt 286 mit
  Jog-Schritten (≈ 4 statt ≈ 24 je Kachel). Dauer je Anfrage ist **nicht gemessen**; der
  Snapshot startet je Kachel `ffmpeg` und liest mindestens 6 Bilder, das kann pro Kachel länger
  dauern als ein Bild einer lokal offenen Kamera.
* Z hat keinen absoluten Pi-Befehl (weiter Jog-Schritte); Belichtung der Pi-Kamera nicht einstellbar.
* Der Pi erlaubt Z-Bewegungen nur relativ zu *einer* gemessenen Oberfläche; bei mehreren
  unterschiedlich hohen Werkstücken gilt die zuletzt gemessene.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_scanprobe.py tests/test_scan_panel.py tests/test_scan_marking.py \
  tests/test_focus_export.py tests/test_focus_multi_region.py
```

Alle Tests laufen mit Fakes (`scanprobe.fakes`: synthetisches Bett, Maschine mit
Positionsfehlern und Tasterausfällen, Kamera mit optionaler Linsenverzeichnung).
