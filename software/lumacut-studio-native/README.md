# LumaCut Studio (Native)

Professionelle Windows-Desktop-App für die LumaCut-Maschine.

- Geschrieben in Python mit PySide6 (Qt)
- Kein Web-UI, echte native Fenster
- Arbeitsfläche 360 × 340 mm (Safezone intern und unsichtbar)
- Scan & Probe Workflow vorbereitet
- Direkte Anbindung an die Pi-API (Status, Home/Jog/Park/Fokus, Not-Aus, Aufträge)

## Starten
```bash
pip install -r requirements.txt
python src/main.py
```

## Bauen (Windows)
```bash
pip install pyinstaller
pyinstaller --windowed --name LumaCutStudio src/main.py
```

## Arbeitsfläche (Canvas)

Code: `src/lumacut_canvas/` (eigenes Paket, Modell ohne Qt-Abhängigkeit).
Eigenständig testen: `python src/canvas_demo.py`.

- **Werkzeuge:** Auswahl (V), Rechteck (R), Ellipse (E), Linie (L), Polygon (P), Freihand (F), Text (T).
  *Umschalt* beim Zeichnen = Quadrat/Kreis/45°-Linie; Klick ohne Ziehen legt
  ein 20-mm-Objekt an. Doppelklick auf Text = Text ändern. Polygon: Klick = Punkt,
  Doppelklick/Enter oder Klick auf den ersten Punkt = schließen, Rücktaste = Punkt weg.
  Freihand: ziehen zeichnet einen offenen Pfad (ohne Raster); beim Loslassen wird er mit
  Ramer-Douglas-Peucker vereinfacht (Toleranz 0,2 mm, `tools.FREEHAND_TOLERANCE_MM`), Esc bricht ab.
- **Bearbeiten:** Verschieben (Maus oder Pfeiltasten 1 mm, *Umschalt* 10 mm),
  Skalieren über 8 Griffe (*Umschalt* = Seitenverhältnis halten), Entf,
  Strg+D duplizieren, Strg+C/V, Strg+Z/Strg+Y, X/Y/B/H in mm in der Eigenschaftsleiste.
- **Drehen:** runder Griff über dem Auswahlrahmen (*Umschalt* = 15°-Schritte),
  Feld „Winkel“ in der Eigenschaftsleiste, Strg+R / Strg+Umschalt+R = ±90°.
  Gedrehte Objekte lassen sich weiter verschieben und entlang ihrer Kanten skalieren;
  Drehung wirkt in Datei, SVG/PNG-Export und G-Code.
- **Gruppen:** Strg+G gruppiert, Strg+Umschalt+G löst eine Ebene der Gruppierung
  (verschachtelte Gruppen möglich). Ein Klick wählt immer die ganze Gruppe;
  Verschieben, Skalieren, Drehen, Löschen und Duplizieren wirken auf die Gruppe.
  Gruppenmitglieder bleiben auf ihren Ebenen (Laserparameter je Ebene).
- **Ansicht:** Mausrad = Zoom (ohne Auswahl um den Cursor, mit Auswahl auf die
  Auswahlmitte zu – sie bleibt stehen bzw. wird zentriert; 0,4–60 px/mm), mittlere Maustaste oder Leertaste+Ziehen = Verschieben,
  Strg+0 = Fläche einpassen, Raster und Fangen (1 mm) umschaltbar, Lineale in mm,
  Cursorposition in mm in der Statusleiste.
- **Ebenen:** Farbe, Name, sichtbar, gesperrt, Reihenfolge; je Ebene
  Leistung (1–100 %), Geschwindigkeit (1–6000 mm/min) und Durchgänge (1–30),
  optional Material/Dicke/Tiefe je Durchgang (siehe „Material-Grundlage“).
  Objekte übernehmen Farbe und Parameter ihrer Ebene. Ausgeblendete Ebenen
  werden nicht gelasert; die unterste Ebene läuft zuerst.
- **Dateien:** Speichern/Öffnen als `*.lumacut.json` (Format `lumacut-canvas`, v3, mm;
  v1/v2-Dateien werden weiter gelesen; Material-Felder werden nur gespeichert, wenn gesetzt),
  Export als SVG oder PNG (Strg+E).
- **An die Maschine:** „Design senden“ (Toolbar) erzeugt Marlin-G-Code
  (`lumacut_canvas/gcode.py`, Regeln wie `marlin-postprocessor.mjs`) und lädt
  ihn über das Maschinen-Panel hoch; gestartet wird erst mit „Start Job“.
- **Rahmen:** „Rahmen“ (*Strg+Umschalt+F*, Rechteck) bzw. „Gummiband-Rahmen“
  (*Alt+Umschalt+F*, konvexe Hülle) oder der Knopf „Rahmen“ im Maschinen-Panel
  fahren den Umriss mit ausgeschaltetem Laser ab (`op=frame`). Der gesendete
  Auftrag bleibt geladen: senden → Rahmen → starten, ohne neu zu senden.
- Die Arbeitsfläche zeigt 0–360 × 0–340 mm. Objekte werden still in der Fläche
  gehalten; der interne Safezone-Versatz wird nur beim Export für die Maschine
  addiert (`lumacut_canvas/workarea.py`).
- **Bekannte Grenzen:** Ungleichmäßiges Skalieren einer Mehrfachauswahl/Gruppe mit
  gedrehten Objekten skaliert diese ohne Scherung (Näherung; gleichmäßig mit
  *Umschalt* ist exakt). Gesperrte/ausgeblendete Gruppenmitglieder werden nicht mitbewegt.

### Material-Grundlage (Durchgänge aus Dicke und Tiefe je Durchgang)

`lumacut_canvas/material.py` (Qt-frei, Tests: `tests/test_material.py`). Feldnamen wie
`lumacut_materials.presets.Preset` (`thickness_mm`, `depth_per_pass_mm`); die
Materialbibliothek bleibt die Quelle für geplante Werte, dieses Modul ist die
schlanke Rechenbasis an der Ebene.

```python
from lumacut_canvas.material import (BUILTIN_MATERIALS, Material, plan_passes,
                                     layer_pass_plan, material_from_preset)
plan_passes(3.0, 0.8)            # passes 4, pass_depths (0.8, 0.8, 0.8, 0.6), total_mm 3.0
ed.apply_material(Material("Birke", 4.0, depth_per_pass_mm=1.0))   # 1 Undo-Schritt, passes = 4
ed.apply_material(m, target_depth_mm=1.5)   # Gravurtiefe statt Durchschnitt
layer_pass_plan(layer)           # mit den eingestellten layer.passes (Override), .reaches_target
```

- Tiefe = `target_depth_mm` oder (wenn 0) `thickness_mm`; `passes = ceil(Tiefe / depth_per_pass_mm)`,
  begrenzt auf 1–30. Abgeleitet, aber überschreibbar: von Hand gesetzte Durchgänge gelten.
- `BUILTIN_MATERIALS` sind **editierbare Startwerte, keine geprüften Empfehlungen** –
  immer erst einen Materialtest machen.
- **G-Code-Hook:** `document_to_gcode(doc, pass_hook=f)` ruft je Durchgang einer geplanten
  Ebene `f(job_layer, index, depth_mm, cumulative_mm)` und fügt die Zeilen nach
  `; PASS i OF n` ein (`gcode.depth_comment_hook` = nur Kommentare). Ohne Hook ist die
  Ausgabe unverändert; die Fokus-Absenkung bleibt `z_step`.
- **UI im Ebenen-Panel** („Material der Ebene“, Tests: `tests/test_material_panel.py`):
  Auswahl „— ohne Material —“, eingebaute Startwerte und – falls `lumacut_materials`
  eigene Presets gespeichert hat – „… (Preset)“ (nur gelesen; `LayersPanel(..., presets=f)`
  liefert eine eigene Quelle, `reload_presets()` liest neu). Felder Dicke, Zieltiefe
  („= Dicke“ bei 0) und Tiefe/Durchgang („aus“ bei 0). Durchgänge folgen automatisch
  (Abzeichen **auto**); von Hand geändert zeigt es **manuell**, „Auto“ setzt zurück.
  Darunter der Tiefenplan je Durchgang, rot mit ⚠, wenn die Zieltiefe nicht erreicht
  wird. Jede Änderung ist ein Undo-Schritt (`SetLayerAttrsCommand`). „manuell“ wird aus
  `passes ≠ ceil(Tiefe/Tiefe je Durchgang)` erkannt (kein eigenes Override-Feld).

### Schnittstellen für andere Module (Scan & Probe)

Alle Koordinaten in Arbeitsflächen-mm (0,0 links oben). Getestet in
`tests/test_integration_hooks.py`.

```python
from lumacut_canvas.overlays import ImageOverlay, PainterOverlay
from lumacut_canvas.integration import add_dock_panel, make_action
from lumacut_canvas.workarea import Rect

ed = window.canvas                                    # CanvasEditor
# Bilder/Höhenkarten UNTER den Objekten (nicht anklickbar, nicht im Export/G-Code)
ed.add_overlay("scan", ImageOverlay(qimage))          # ganze Fläche 360 × 340 mm
ed.add_overlay("hoehe", ImageOverlay(heat, Rect(0, 0, 180, 170), opacity=0.6), z=10)
ed.add_overlay("marken", PainterOverlay(lambda painter, work: ...), z=20)
ed.overlay("hoehe").visible = False; ed.refresh_overlays()
ed.remove_overlay("scan")
# Bereich (ROI) wählen: nächster Mauszug, auf die Fläche begrenzt, Esc bricht ab
ed.roiSelected.connect(lambda x, y, w, h: ...)        # mm
ed.roiCancelled.connect(...)
ed.request_roi()                                      # ed.roi / ed.clear_roi()
# Panels und Aktionen aus main.py
dock = add_dock_panel(window, panel, "Scan & Probe")  # QDockWidget, objectName "dock_scan___probe"
ed.add_toolbar_action(make_action(window, "Bereich scannen", ed.request_roi,
                                  shortcut="Ctrl+Shift+B"), name="scan_roi")
```

`set_backdrop(img)` bleibt als einfacher Vollflächen-Hintergrund erhalten; Overlays
werden darüber und unter Raster und Objekten gezeichnet. Ein Fehler in einem
Overlay wird geloggt und bricht das Zeichnen nicht ab.

## Maschinenanbindung (Pi-API)

Das Panel **Maschine** (rechte Spalte) spricht direkt mit dem Flask-Dienst des
Pi 400 (`pi400/marlin/web.py`). Code: `src/machine/`
(`client.py` HTTP-Client nur mit stdlib, `worker.py` Status-Poller und Befehle
in eigenen Threads, `panel.py` Oberfläche, `settings.py` Einstellungen).

**Verbinden**
- Adresse: Standard `http://lumacut.local:8080`; `lumacut.local` oder eine IP
  genügt, `http://` und Port `8080` werden ergänzt.
- Schlüssel: wird bei jeder Anfrage als Header `X-LumaCut-Key` gesendet,
  nie geloggt und im Feld verdeckt angezeigt. Alternativ Umgebungsvariable
  `LUMACUT_KEY` (hat Vorrang und wird nicht gespeichert).
- Adresse, Schlüssel und „Automatisch verbinden“ werden per `QSettings`
  gespeichert (Windows: `HKCU\Software\LumaCut\LumaCut Studio`, Schlüssel
  im Klartext – wer das nicht will, nutzt `LUMACUT_KEY`).

**Statusanzeige** (farbig): Verbindung (getrennt / verbinde / verbunden /
Fehler / Schlüssel abgelehnt), SKR-USB, X/Y/Z, Homed, Laser (aktiv / aus /
unbekannt), Besitzer, Fokus-Z, Auftrag mit Fortschritt (Zeile/Gesamt),
letzter Fehler. Der Status wird jede Sekunde im Hintergrund abgefragt, und
die Oberfläche blockiert nie. Ist der letzte gute Status älter als 3 s (der Pi
antwortet während Home/Park/Abtasten erst danach), zeigt das Badge „Status
N s alt“, und alle Knöpfe außer NOT-AUS sind gesperrt.

**Bedienung → API**

| Knopf | Anfrage |
| --- | --- |
| NOT-AUS (Panel, Toolbar, Taste *Pause*) | `POST /api/action op=estop`: eigener Thread, 3 s pro Versuch, bis zu 3 Versuche bei Netzfehlern (zusammen höchstens ≈ 4 s, kein System-Proxy), auch während Home/Probe und ohne Verbindung; Rückmeldung „bestätigt“ / „NICHT bestätigt“ unter dem Knopf |
| Notstopp quittieren | `op=estop_reset` (mit Rückfrage; danach neu referenzieren) |
| Home | `op=home` |
| Jog X±/Y±/Z± | `op=jog axis=X\|Y\|Z distance=±0.1\|1\|10` (nur gehomed) |
| Fokus (G30) | `op=probe` – Pi merkt sich die Oberfläche und fährt vor dem ersten Laserstrich selbst auf Fokushöhe |
| Park | `op=park`: Laser aus, Z-Rückzug, X0/Y0 (nur gehomed) |
| Senden | `POST /api/upload` (multipart `file`, .gcode/.gc/.nc, max. 32 MB) |
| Starten / Ein-Klick | `op=start name=…` / `op=autorun name=…` (mit Rückfrage) |
| Rahmen (Rechteck / Gummiband), *Strg+Umschalt+F* / *Alt+Umschalt+F* | `op=frame gcode=… mode=box\|hull`: Umriss mit Laser aus, ohne Upload; der gesendete Auftrag bleibt geladen (nur gehomed, nicht während eines Auftrags; mit Rückfrage) |
| Abbrechen | `op=abort` (Auftrag oder Rahmenfahrt) |

Fehler des Pi (`{"error": …}`) erscheinen im Panel unter „Letzte Meldung“.

Alle Aufrufe mit Payload, Antwortfeldern, Fehlercodes und Zeitlimits, dazu
Zustandsautomat, NOT-AUS-Verhalten und Einstellungen:
**[docs/MACHINE_API.md](docs/MACHINE_API.md)**.

**Hinweise / offene Punkte im Pi-Dienst**
- Der Pi prüft `X-LumaCut-Key` derzeit nicht. Die App sendet ihn trotzdem und
  zeigt HTTP 401/403 als „Schlüssel abgelehnt“ an, sobald der Pi ihn prüft.
- `op=park` und `op=frame` sind jetzt in `pi400/marlin/web.py` enthalten.
  Ein älterer Pi-Dienst meldet „bietet noch kein Parken über die API“ bzw.
  „bietet noch keine Rahmenfahrt über die API“, bis er aktualisiert ist.
- `/api/status` wartet auf die Maschinensperre und liefert deshalb während
  Home/Park/Abtasten keine Live-Position.

## Kamera-Scan und Höhenmesh

Kachel-Scan, Objekterkennung, Mehrbereichs-Proben, Höhenmeshes und
Fokuskorrektur: siehe [docs/SCAN_PROBE.md](docs/SCAN_PROBE.md) (`src/scanprobe/`).

## Materialbibliothek

*Material → Materialbibliothek …*: Startwerte (Leistung, mm/min, Durchgänge,
Fokus-Absenkung je Durchgang) für 25 Materialien und LaserTree LT-80W
(10 W optisch) bzw. 5/10/20/40-W-Dioden auf die aktive Ebene anwenden,
Presets speichern, 3D-Relief aus Graustufenbild. Warnliste für nicht
laserbare Materialien. Siehe [docs/MATERIALS.md](docs/MATERIALS.md)
(`src/lumacut_materials/`).

## Tests

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests
```

Die Maschinen-Tests (`tests/test_machine_*.py`) laufen gegen einen lokalen
Fake-Pi (`tests/fake_pi.py`) und brauchen keine Hardware.

Canvas-Tests (`tests/test_model.py`, `test_layers.py`, `test_serialization.py`,
`test_undo.py`, `test_editor.py`, `test_gcode.py`) laufen ebenfalls offscreen.
Unter Windows (PowerShell):

```powershell
pip install -r requirements.txt -r requirements-dev.txt
$env:QT_QPA_PLATFORM = "offscreen"; python -m pytest tests
```
