# LumaCut: Vereinfachung Windows- und Android-App (2026-10-26)

**Ziel:** Beide Apps so einfach machen, dass ein Neuling Material wählt, Motive platziert und den Auftrag startet. Alles andere passiert automatisch.

Dieses Dokument ist die gemeinsame Quelle für Grok-Agents und Claude. Änderungen bitte hier und in den Commit-Nachrichten dokumentieren.

## 1. Gewünschter Ablauf (ein Klick)

1. Material auswählen (Stärke, Einstellungen kommen aus der Pi-Datenbank).
2. Motive platzieren und bearbeiten.
3. **Auftrag starten** – fertig.

Der Rest läuft automatisch:
- Referenzfahrt (XY zuerst, dann Z, Rückzug)
- Schnelles Probing / Höhenmesh (immer, keine Auswahl)
- Fokus
- Job
- Parken

**Kein** manueller Schritt für Referenzieren oder „mit/ohne Probing“. Probing ist immer dabei und soll schnell sein.

## 2. Nullpunkt und Achsen

- **X/Y 0,0 ist oben rechts** (Seite der Endschalter / Tür auf der anderen Seite).
- Bisherige Darstellung (0,0 unten links) ist falsch für diese Maschine.
- Arbeitsfläche 360 × 340 mm, Safezone 30 mm bleibt intern und unsichtbar.

### 2.1 Nullpunkt-Konvention – verifiziert (Machine-Agent, 2026-10-26)

Geprüft gegen `firmware/marlin/build.py`, die Upstream-Vorlage, die es patcht
(`Configurations` release-2.1.2.9, `config/examples/AnyCubic/Mega Zero/BigTreeTech SKR Mini MZ V1.0/Configuration.h`),
`pi400/marlin/transport.py`, `web.py`, `placement.py` und den Studio-Code.

**Ergebnis: Maschine und Pi passen schon. Es braucht keine Firmware-Änderung.
Gespiegelt werden muss nur die Darstellung in den Apps, und zwar nur X.**

**(1) Meldet Marlin/Pi die Positionen so (X0 Y0 an den Endschaltern, positive Achsen ins Bett)?** Ja.
- Die Firmware nutzt nur MIN-Endschalter (`USE_XMIN_PLUG`, `USE_YMIN_PLUG`, `USE_ZMIN_PLUG`; MAX auskommentiert) und `X_HOME_DIR -1`, `Y_HOME_DIR -1` aus der Vorlage. build.py ändert keine dieser Zeilen.
- Weitere Werte: `X_MIN_POS 0` (gepatcht), `Y_MIN_POS 0` (Vorlage), `X_BED_SIZE 390`, `Y_BED_SIZE 370`, `X/Y_MAX_POS = BED_SIZE`.
- Daraus folgt: Nach `G28 X Y` steht der Kopf an den Schaltern auf **X0 Y0**. Positive Werte führen **von den Schaltern weg ins Bett**, bis X390 / Y370. `M114` und `/api/status` → `position` melden genau diese Maschinen-mm.
- Pi und Machine-Panel kippen nichts und versetzen nichts: kein G92, kein Vorzeichenwechsel. `placement.translate` verschiebt nur.
- Mit den Schaltern **oben rechts** heißt das: **+X = nach links, +Y = nach unten/vorne Richtung Tür.** ⚠ Hardware: Wo die Schalter sitzen, steht in keiner Konfigurationsdatei; das kommt aus der Angabe des Nutzers. `INVERT_X_DIR`/`INVERT_Y_DIR false` ist laut build.py „am Gerät geprüft“. Probe am Gerät: referenzieren, `X +10` joggen → Kopf fährt nach links; `Y +10` → Kopf fährt zur Tür.
- **Joggen:** `op=jog` schickt `G91` + `G0 X±d`. „X +“ fährt von den Schaltern weg (nach links), „Y +“ nach vorne. Falsch beschriftet sind nur die Pfeil-Layouts in den UIs, siehe (3).
- **Parken:** `park_safezone` fährt `G0 X0 Y0`, also in die Schalterecke oben rechts.
- **Homing:** Z homt an `Z_SAFE_HOMING_X/Y_POINT 0/0`, ebenfalls in der Schalterecke.
- **Abtastpunkte, Höhenmesh, Kameramosaik:** Alles liegt in denselben Maschinen-mm.
  - `probe_workpiece` rechnet `Kopf = Laserpunkt − probe_xy_offset`, mit Vorzeichen in Maschinenrichtung.
  - `scanprobe/stitch.py` legt Mosaikspalte 0 auf das **kleinste X** (jetzt rechts) und Zeile 0 auf das kleinste Y (oben).
  - Die Kamerakalibrierung (`flip_x`/`flip_y`) ist auf Maschinen-+X/+Y bezogen und bleibt gültig.

**(2) Wirkt der Safezone-Versatz +30/+30 in derselben Richtung?** Ja.
- Die Sperrzone ist `X < 30 oder Y < 30` in Maschinen-mm (`safe_zone_xy_mm`, `_xy_cut_guard_locked`, `preflight`). Das sind die beiden 30-mm-Streifen **an den Schalterkanten**: der rechte Rand und der obere/hintere Rand.
- Die Arbeitsfläche ist Maschine X30–390 / Y30–370. Ihre Ecke oben rechts ist Maschine **(30, 30)**.
- Mit Canvas-Koordinaten (Ursprung oben rechts, u nach links, v nach unten) gilt `Maschine = (u + 30, v + 30)`. Das ist genau das heutige `to_machine(x, y) = (x + 30, y + 30)`, ohne zusätzliches Kippen.
- Für Code, der in **Bildschirm**-Koordinaten von links nach rechts zeichnet (Bildschirm-x von 0 links bis 360 rechts):
  - `Maschine_x = 390 − Bildschirm_x`
  - `Maschine_y = 30 + Bildschirm_y`
  - zurück: `Bildschirm_x = 390 − Maschine_x`

**(3) Wo wird heute unten links (oder ungespiegeltes X) angenommen?**
- **Studio-Canvas (Canvas-Agent):**
  - `lumacut_canvas/workarea.py` dokumentiert „Ursprung oben links, X nach rechts“. Y stimmt schon (oben = kleines Y = Schalterseite), **nur X ist gespiegelt**. Alles bisher Exportierte lief also seitenverkehrt in X: Schrift kam spiegelverkehrt.
  - Betroffen beim Umstellen: `export.py` (`to_machine`), `path_preview.py` (`from_machine`), `overlays.py` („0,0 = links oben“) und alle Bilder.
- **Bilder über dem Canvas:**
  - `scanprobe/panel.py`: `mosaic_to_work_image` erzeugt ein Bild mit Spalte 0 = Maschine X30. `heatmap_rgba` und `render_heatmap` machen es genauso (Spalte 0 = kleinstes X).
  - `set_backdrop` und `items.py`/`export.py` zeichnen `drawImage` links→rechts.
  - Wenn der Canvas die Bildschirm-x-Richtung spiegelt, müssen diese Bilder **horizontal gespiegelt** werden (`cv2.flip(img, 1)` oder die Pixelmatrix `[[-s,0,…],…]`). Spiegelt der Canvas über eine View-Transformation (`scale(-1, 1)`), stehen Text, Bilder und Marker verkehrt. Davon rate ich ab.
  - Die Rückfall-Umrechnung `to_machine`/`from_machine` in `scanprobe/panel.py` (Zeilen 53–57) muss mitziehen.
- **Studio-Machine-Panel (meins, ich passe es an):** Das Jog-Kreuz in `machine/panel.py` legt „Y +“ nach oben, „Y −“ nach unten, „X −“ nach links und „X +“ nach rechts. Das ist ein Bild mit Ursprung unten links. Richtig ist: X+ links, X− rechts, Y+ unten, Y− oben. Dazu kommen die Anker-Beschriftungen (siehe unten).
- **Pi-Platzierungsanker (meins):**
  - `placement.ANCHORS` definiert heute `tl` = (kleinstes X, kleinstes Y), also links = kleines X.
  - Physisch ist kleines X jetzt **rechts**. Ich stelle den Pi um: `tr` = (xmin, ymin) = Schalterecke, `tl` = (xmax, ymin), `br` = (xmin, ymax), `bl` = (xmax, ymax). `center` bleibt.
  - Folge: Ein Client, der den Ankernamen nach der sichtbaren Ecke wählt, bekommt die physisch richtige Ecke.
  - **Meldung an den Canvas-Agent:** Wenn ihr Anker aus Canvas-Ecken ableitet, nennt sie nach der sichtbaren Lage (oben rechts = `tr`).
- **Pi-Web-UI (Web-UI-Agent, `index.html`):**
  - Das Bett-SVG nutzt `translate(0,H) scale(1,-1)`, also Ursprung unten links, Y nach oben. Die Safezone liegt dadurch links/unten.
  - Richtig wäre `translate(W,0) scale(-1,1)`: Ursprung oben rechts, X nach links, Y nach unten. Die Achsbeschriftungen müssen ungespiegelt mitgezogen werden.
  - Jog-Kreuz und Tastatur `KEYS`: richtig ist ArrowLeft = X+, ArrowRight = X−, ArrowDown = Y+, ArrowUp = Y−. Das Layout analog zu Studio.
- **Android (Android-Agent):**
  - `core/Geometry.kt` `Work.toMachine` = (x+30, y+30). Laut `docs/ANDROID_APP.md` gilt „Nullpunkt oben links, Y nach unten“. Wie im Studio ist nur X gespiegelt.
  - Gleiche Korrektur nötig: Darstellung spiegeln, `Work.toMachine` bleibt, wenn die Work-Koordinaten u nach links laufen. Dazu Jog-Kreuz und Scan-Bilder.
- **Unverändert richtig:** Pi-Grenzen (`preflight`, `frame_program` X0..390/Y0..370, `move_to`, Abtastbereich X30..390/Y30..370), Parkposition, Homing, Kamerakalibrierung, Höhenmesh-Daten, `job_geometry`. Alles läuft in Maschinen-mm.

**Entscheidung für den Nutzer: keine.** Eine Firmware-Änderung (zum Beispiel `X_HOME_DIR`/`INVERT_X_DIR` umdrehen, damit Maschinen-X nach rechts wächst) wäre die Alternative. Davon rate ich ab, weil:
- die Schalter physisch an MIN hängen;
- der Pi, alle Grenzen, die Safezone, der Park und die Kalibrierwerte (Tasterversatz, Kamera) neu eingemessen werden müssten.

Die Apps bilden einfach die echte Maschine ab.

### 2.2 Umgesetzt (Maschinenseite) und Übergabe an den Canvas-Agent

**Status: erledigt** auf der Maschinenseite. ⚠ Hardware: Die Jog-Richtungen müssen einmal am Gerät geprüft werden.

**Pi (`placement.py`, `web.py`):**
- Die Ankernamen bezeichnen jetzt die **sichtbare Ecke von vorne**:
  - `tr` = (kleinstes X, kleinstes Y) = Schalterecke; das ist auch der neue Standard.
  - `tl` = (größtes X, kleinstes Y).
  - `br` = (kleinstes X, größtes Y).
  - `bl` = (größtes X, größtes Y).
- `/api/status` und `status.origin` melden `coord_convention: "origin_top_right"`.

**Studio-Machine-Panel:**
- Das Jog-Kreuz entspricht der Ansicht von vorne: „← X +“ links, „X − →“ rechts, „↑ Y −“ oben, „↓ Y +“ unten.
- Die Positionsanzeige zeigt Maschinen-mm. Ein Tooltip erklärt Nullpunkt und Richtungen.
- Standardanker ist „Oben rechts“.

**Versionierung (Entscheidung):** Es gibt keine allgemeine `api_version`, sondern das gezielte Feld `coord_convention`.
- Fehlt das Feld, kennt Studio die alte Bedeutung („l“ = kleines X). `machine.client.wire_anchor()` tauscht dann links/rechts, also passt neues Studio auch zu altem Pi.
- Altes Studio und neuer Pi vertauschen dagegen die Ecken links/rechts. Deshalb gilt der **Pi-Update-Hinweis: Studio und Pi gemeinsam aktualisieren.**

**Übergabe an den Canvas-Agent (Ankernamen):**
- Wenn Canvas, Kamera-Scan oder Motiv-Ausrichtung einen Bezugspunkt an `MachinePanel.set_job_origin(origin, anchor)` geben, ist der Name die **sichtbare Ecke im neuen Canvas**: oben rechts = `tr` = Nullpunkt-Ecke.
- Umrechnen müsst ihr nichts: Panel und Client übersetzen für ältere Pis selbst.
- Für Maschinenpunkte (`set_user_origin(x, y)`) bleibt es bei Maschinen-mm. Aus Canvas-Koordinaten (u nach links, v nach unten) ist das `to_machine(u, v) = (u + 30, v + 30)`.
- Tests: `software/lumacut-studio-native/tests/test_machine_orientation.py`, `tests/test_job_placement.py`.

**Übergaben an andere Agents:**
- **Web-UI-Agent (Pi-Web-UI):** Jog-Kreuz und Tastatur spiegeln, Bett-SVG mit Ursprung oben rechts, siehe 2.1 (3).
- **Android-Agent:** Ankernamen als sichtbare Ecke senden; neue Pis melden `coord_convention`.

## 3. Kamera-Scan

- Optional, ausgelöst durch einen **einzigen Button** in beiden Apps.
- Kein Pflicht-Schritt im normalen Auftrag.
- Scan bei fester Höhe, Kachelweise, Ergebnis als Hintergrund zum genauen Platzieren.

## 4. Materialdatenbank auf dem Pi

- Materialliste und Einstellungen (Leistung, Geschwindigkeit, Durchgänge, Z-Schritt) liegen auf dem Pi.
- Windows-App, Android-App und Pi-Web-UI nutzen dieselbe Quelle.
- Änderung in einer App gilt für alle.

## 5. UI-Aufräumen (Windows + Android)

- Weniger Einstellungen und Buttons auf der Hauptansicht.
- Große, klare Aktionen: Material, Design, Start.
- Erweiterte Optionen (Kerf, Haltestege, Füllung etc.) hinter „Mehr“ oder in einem eigenen Bereich.
- Touch-freundlich, responsiv, für Neulinge verständlich.

## 6. Zusammenarbeit

- **Kommunikation über GitHub** (Commits, dieses Dokument, Issues/PRs falls nötig).
- Agents und Claude ändern keine Dateien des anderen ohne Absprache.
- Vor jedem Push: `git pull --rebase origin main`.
- Kleine, klare Commits mit Bezug auf dieses Dokument.

## 7. Offene Punkte / Zuordnung

| Thema | Zuständig | Status |
|---|---|---|
| Ein-Klick-Auftrag (Homing + Probing + Fokus + Job) | Pi-Ablauf (`op=autorun`, Abtastraster, Höhenkorrektur auf dem Pi): **Claude, Session pi-automatik**; Start-Knopf in Studio: Machine | in Arbeit (Pi) |
| Nullpunkt oben rechts | Canvas + Machine | offen |
| Kamera-Scan als Button | Scan Probe | offen |
| Materialdatenbank auf dem Pi | Pi-API `/api/materials`: **Claude, Session pi-automatik** (Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` Abschnitt 3); Anbindung in Studio: Materials | in Arbeit (Pi) |
| Cleaner UI Windows | Canvas | offen |
| Cleaner UI Android | Claude, Session android | in Arbeit |

## 8. Nächste Schritte

1. Pi: Material-API und Speicherort definieren und dokumentieren.
2. Studio: Hauptansicht aufräumen, Start-Button macht den kompletten Ablauf.
3. Nullpunkt-Korrektur in Canvas und G-Code.
4. Android: gleiche Vereinfachung und Anbindung an die Pi-Materialdatenbank.
