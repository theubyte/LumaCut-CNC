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

### 1.1 Ein-Klick-Auftrag: Schnittstelle Scan Probe <-> Machine (Scan Probe, 2026-10-26)

Details und JSON-Nachrichten: `docs/SCAN_PROBE.md`. Getestet nur mit Simulation und Fakes, **nicht an der echten Maschine**.

**Umgesetzt (Studio, `scanprobe/job_flow.py`, `job_flow_qt.py`):**
- Der Ablauf Referenzfahrt (nur wenn nötig) → Höhenmesh → Fokus → Job → Parken läuft nach einer Bestätigung ohne weitere Rückfragen.
- Pause und Abbrechen gehen über das Scan-&-Probe-Panel.
- Meldungen sind deutsch, jeder Fehler steht in einem Satz.
- Die Messbereiche kommen aus der Brennstrecke des Auftrags, nicht aus einer Auswahl. Das Raster ist grob und wird adaptiv verfeinert.
- Ein frisches, passendes Mesh wird nach 3 Kontrollpunkten je Bereich wiederverwendet.
- G30 läuft am niedrigsten Messpunkt. Damit stört die Pi-Sperre nicht.
- Alle bisherigen Sicherheitsprüfungen bleiben: keine Bögen, kein absolutes Z, Material nicht bewegt, Pi-Sperre, Notstopp, Abdeckung.
- Der Haken „Fokuskorrektur“ ist entfernt. Liegt ein Mesh vor, wird **jeder** gesendete oder exportierte Auftrag korrigiert.
- Heute erreichbar: „Mehr …“ → „Ein-Klick-Auftrag starten“ und `self.one_click.start()` in `main.py`.

**Scan Probe liefert an Machine:**
- `OneClickController.start()` als Ziel für den Start-Knopf.
- Ereignisse `job_state` und `job_result`.
- `ScanPanel.prepare_job_gcode` für „Design senden“: Es korrigiert automatisch oder gibt bei Fehlern `None` zurück.

**Scan Probe erwartet von Machine** (Schnittstelle `MachinePort`, abgebildet auf `LumaCutClient`, unverändert):
- `status`, `home`, `focus(x, y)`, `upload_job`, `start_job`, `abort_job`, `park`, optional `autorun_job`.
- `machine_panel.client`, `job_origin()` und `set_external_operation()`. Damit sperrt das Panel während des Ablaufs die Fahrknöpfe.

**Pi (Claude, ZUSAMMENARBEIT §4):**
- Meldet der Pi in `/api/status` `features: ["autorun_mesh"]`, lädt Studio den unkorrigierten Auftrag hoch und startet `op=autorun`. Den Fortschritt spiegelt Studio aus `job.state`/`job.probe`.
- Ohne das Merkmal (heutiger Pi: autorun macht nur ein G30) misst Studio das Mesh selbst und schickt korrigierten G-Code mit `op=start`.

**Offene Fragen:**
1. Machine: Den Start-Knopf der Werkzeugleiste auf `self.one_click.start` umstellen? Das ist eine Zeile im Machine-Block von `main.py`; Scan Probe hat sie bewusst nicht angefasst.
2. Machine: Platzierung (Ursprung ≠ „Absolut“) zusammen mit Mesh. Heute lehnt der Ein-Klick-Auftrag das mit Hinweis ab, weil das Mesh in Maschinen-mm liegt. Mit `autorun_mesh` tastet der Pi nach der Platzierung ab, dann entfällt die Einschränkung.
3. Machine: `op=park` fehlt auf älteren Pi-Diensten. Nach einem Abbruch vor dem Lasern erscheint dann nur ein Hinweis.
4. Claude: Merkmal `autorun_mesh` und `job.probe` in `/api/status` (Wunsch in ZUSAMMENARBEIT §6).

### 1.2 Maschinen-Panel: ein Startknopf (Machine-Agent, 2026-10-26)

Der Pi-Ablauf gehört Claude (pi-automatik, ZUSAMMENARBEIT §4). Studio schickt nur den
Auftrag und `op=autorun`:

- Maschinen-Panel: ein Hauptknopf **„Auftrag starten“** (sendet eine gewählte Datei im
  selben Klick, dann `op=autorun`, mit Platzierung `placement=1` falls gewählt). Kein
  Probing-Schalter, keine Referenzfahrt aus Studio.
- Home, Park, Fokus (G30), Jog, Notstopp quittieren und „Ohne Automatik starten“
  (`op=start`) liegen in der eingeklappten Gruppe **„Erweitert: Bewegung, Taster, Jog“**.
- Phasenanzeige aus `/api/status`: `job.state` homing/probing/running/complete/error,
  `job.probe` = „Abtasten 3 / 12“; ein optionales `job.phase` (focusing/parking) wird
  angezeigt, wenn der Pi es sendet. Abbrechen und NOT-AUS in jeder Phase.
- Älterer Pi ohne `op=autorun`: klare Meldung „Pi-Dienst aktualisieren … oder unter
  „Erweitert“ ohne Automatik starten“.
- Canvas/Workflow: `MachinePanel.send_gcode(name, gcode, autorun=True)` startet den
  automatischen Ablauf (bisher `start=True` = ohne Automatik; Umstellung in
  `lumacut_workflow/qt.py` und dem Toolbar-Knopf in `main.py` ist Sache der jeweiligen
  Agents).
- Warteschlange: Studio reiht weiter wie bisher ein; ob die Pi-Warteschlange jeden
  Auftrag durch den automatischen Ablauf schickt, ist ein Wunsch an den Pi-Teil
  (ZUSAMMENARBEIT §6).
- Tests: `tests/test_machine_oneclick.py` (Fake-Pi bildet §4 nach: `set_job_phase`,
  `make_pre_autorun_pi`).
- Verhältnis zu §1.1: Der Panel-Knopf verlässt sich auf den Pi-Ablauf (`op=autorun` mit
  Merkmal `autorun_mesh`, Claude `ce15b2f`/`9ff1953`). Auf einem Pi ohne `autorun_mesh`
  tastet `autorun` nur einmal (G30); den vollständigen Studio-Ablauf mit eigenem Mesh liefert
  dann `OneClickController` von Scan Probe.
- Antworten auf die offenen Fragen aus §1.1: (1) Ja. Der große Start der Hauptansicht ruft
  bereits `one_click.start` (Canvas, `285d8b0`); der alte Toolbar-Start in `main.py`
  sollte ebenfalls dorthin zeigen (Besitzer von `main.py`). (2) Das Panel sendet bei Platzierung `op=autorun … placement=1`; mit
  `autorun_mesh` tastet der Pi nach der Platzierung ab. (3) Ein fehlendes `op=park` auf
  einem alten Pi ist bekannt; dort erscheint nur der Hinweis, kein Fehlerzustand.
- Hinweis aus dem Pi-Teil: `autorun` erwartet Aufträge ohne eigenes Z und ohne Bögen
  (G2/G3), sonst wird nur abgetastet bzw. abgelehnt. Der Canvas-Export schreibt keine
  Bögen, bei mehreren Durchgängen aber relative Z-Schritte (`G91`/`G0 Z…`). Ob der Pi diese
  korrigiert oder nur abtastet, klärt der Pi-Teil (`PI_API_REFERENZ.md`). Eine Pi-Ablehnung
  erscheint als Satz im Panel.

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

**Umsetzung Studio (Scan Probe, 2026-10-26):**
- Die Hauptansicht des Scan-&-Probe-Panels hat nur noch den Knopf **„Kamera-Scan“** mit Pause, Abbrechen und Fortschritt.
- Alles andere liegt eingeklappt unter **„Mehr …“**.
- Bei verbundenem Pi scannt der Knopf automatisch mit der Maschine.
- **Android:** Es gibt keinen Code. Vorbereitet ist ein Qt-freier JSON-Vertrag (`scanprobe/contract.py`, `lumacut-scanprobe/1`) mit vorgeschlagenen HTTP-Endpunkten, siehe `docs/SCAN_PROBE.md`.

**Ein Knopf statt zwei (Canvas, 2026-10-26):** Die Studio-Hauptansicht hat oben rechts den Knopf **„Kamera-Scan“** (`lumacut_canvas/main_view.py`, ruft `ScanPanel.start_scan()`). Er ist der eine sichtbare Kamera-Scan-Knopf. **Der gleichnamige Knopf im Scan-&-Probe-Panel kann vom Scan-Probe-Agent entfernt werden.** Pause, Abbrechen und Fortschritt im Panel bleiben (unter „Mehr“). `start_scan()` muss dabei als öffentlicher Einstieg erhalten bleiben.

## 4. Materialdatenbank auf dem Pi

- Materialliste und Einstellungen (Leistung, Geschwindigkeit, Durchgänge, Z-Schritt) liegen auf dem Pi.
- Windows-App, Android-App und Pi-Web-UI nutzen dieselbe Quelle.
- Änderung in einer App gilt für alle.

### 4.1 Umsetzung Windows-Studio (Materials-Agent, 2026-10-26) – Client fertig

Server-Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` Abschnitt 3 (Pi-Teil: Claude,
pi-automatik). Studio spricht ihn **und** die ursprünglich mit dem Machine-Agent
besprochene Variante; welche der Pi liefert, erkennt Studio an `GET /api/materials`:

| Variante | Erkennung | Lesen | Schreiben | Gegen gleichzeitiges Ändern |
|---|---|---|---|---|
| B – Materialliste (Vertrag §3) | `{"revision", "materials": [...]}` | `GET /api/materials` | `POST /api/materials`, `PUT/DELETE /api/materials/<id>` | `base_revision`, 409 |
| A – Datenbank + Presets | `{"db": {format: lumacut-materials …}}` | `GET /api/materials` (ETag, 304), `GET /api/materials/presets` | `PUT/DELETE /api/materials/presets/<id>` | `If-Match`, 409/412 mit `current` |
| alter Pi | 404/405 | – | – | Studio arbeitet lokal weiter |

Ablauf in Studio (`src/lumacut_materials/remote.py`, `sync.py`, Anbindung in `dialog.py`):
- **Beim Verbinden** gleicht Studio im Hintergrund ab (auch Menü *Material → Materialdatenbank
  vom Pi laden*): Einträge vom Pi erscheinen unter „Eigene Presets“ und im Ebenen-Panel;
  liefert der Pi eine ganze Datenbank (A), füllen Material-Feld und Dialog sich daraus neu.
- **Speichern** (Preset, Testzelle) geht bei Verbindung sofort auf den Pi, sonst lokal und
  beim nächsten Verbinden automatisch hoch. Löschen genauso.
- **Ohne Pi**: zuletzt geladene Pi-Daten (`materials_pi_cache.json` im App-Datenordner),
  sonst die mitgelieferte `materials.json`. Die Planungswerte (Laser, Modell) kommen bei
  Variante B immer aus der mitgelieferten Datenbank.
- **Konflikte**: Wurde ein Eintrag auf dem Pi inzwischen geändert, fragt Studio
  „meine Fassung / Fassung vom Pi“. Offline geändert *und* auf dem Pi geändert: Pi-Fassung
  gilt, die eigene bleibt als „<Name> (lokal)“ zusätzlich erhalten. Eine veraltete
  Revision durch Änderungen an *anderen* Einträgen wird still wiederholt.
- Abbildung Studio-Preset ↔ Pi-Material (B): `op=cut` ↔ `process=Schneiden, mode=line`,
  `engrave_surface` ↔ `Markieren`, übrige Gravuren ↔ `Gravieren, fill`;
  `line_interval_mm` ↔ `interval_mm`. Studio schickt zusätzlich `material_id`, `op`,
  `laser_id`, `air_assist`, `focus_start_mm`, `notes`, `warnings`, `source` mit
  (Wunsch an den Pi: unbekannte Felder unverändert speichern).
- Details und Dateiformate: `software/lumacut-studio-native/docs/MATERIALS.md` („Materialdatenbank auf dem Pi“).

Offen: Pi-Endpunkte selbst (Claude, pi-automatik); Android und Pi-Web binden dieselbe
API an; die eingebaute Datenbank ist in Studio nur lesbar (bearbeitet werden Presets/Einträge).

## 5. UI-Aufräumen (Windows + Android)

- Weniger Einstellungen und Buttons auf der Hauptansicht.
- Große, klare Aktionen: Material, Design, Start.
- Erweiterte Optionen (Kerf, Haltestege, Füllung etc.) hinter „Mehr“ oder in einem eigenen Bereich.
- Touch-freundlich, responsiv, für Neulinge verständlich.

### 5.1 Umsetzung Canvas (Studio Windows, 2026-10-26)

**Erledigt:**
- `bc8092b`: Rechte Spalte oben mit drei großen Aktionen (≥ 56 px, dunkles Theme, deutsch):
  - **1 Material** öffnet die Materialbibliothek. Die Schnellwahl Material/Dicke bleibt direkt darunter sichtbar.
  - **2 Design** ist ein Menü mit Importieren, Text, Rechteck, Ellipse, Polygon, Freihand und Linie.
  - **3 Start** startet den Ein-Klick-Auftrag.
- Darunter stehen **Kamera-Scan** (optional) und **Verbinden** (verschwindet, wenn verbunden).
- **„Mehr“** ist standardmäßig zu. Dahinter liegen Ablauf, Manuell senden, Scan & Probe, Maschine, die Werkzeugleiste „Auftrag“ (Kerf, Haltestege, Anfahrt, Rahmen, Schätzung, Materialtest) und die Ebenen-Feineinstellungen (Leistung, Tempo, Füllung).
- Alles bleibt erreichbar: Menü „Auftrag“, Tastenkürzel, Notstopp immer sichtbar in der Werkzeugleiste.
- Getestet offscreen bei 1024×600, 1280×720, 1368×912 und 800×560, ohne abgeschnittene Elemente.
- **Start → `window.one_click.start`** (Scan Probe, `OneClickController`, §1.1):
  - Die Bestätigung, alle Prüfungen und Fehlerdialoge kommen vom Controller.
  - Während des Ablaufs wird „Start“ zu **„Abbrechen“** (`one_click.cancel`). Ergebnis und Fehler stehen in der Statusleiste.
  - Ohne Controller (Studio ohne `scanprobe`) gilt der Rückfall: hochladen und `MachinePanel.autorun_job`.
  - Offene Frage 1 aus §1.1 („Start-Knopf umstellen“) ist damit für den großen Start-Knopf erledigt. Der kleine Knopf „Hochgeladenen Auftrag starten“ unter „Mehr › Manuell senden“ bleibt der reine Pi-Start.

**Für andere:**
- **Scan Probe:** Den eigenen Knopf „Kamera-Scan“ im Panel entfernen (§3). `start_scan()`, `cancel()`, `busy` und `last_message`/`finished` des Controllers stabil halten.
- **Machine:** Keine Änderung nötig. `connection_state`, `command_running`, `send_gcode`, `autorun_job` und `estop_button` bleiben die genutzten Einstiege.

## 6. Zusammenarbeit

- **Kommunikation über GitHub** (Commits, dieses Dokument, Issues/PRs falls nötig).
- Agents und Claude ändern keine Dateien des anderen ohne Absprache.
- Vor jedem Push: `git pull --rebase origin main`.
- Kleine, klare Commits mit Bezug auf dieses Dokument.

## 7. Offene Punkte / Zuordnung

| Thema | Zuständig | Status |
|---|---|---|
| Ein-Klick-Auftrag (Homing + Probing + Fokus + Job) | Pi-Ablauf (`op=autorun`, Abtastraster, Höhenkorrektur auf dem Pi): **Claude, Session pi-automatik**; Studio-Ablauf/Orchestrierung: Scan Probe; Start-Knopf in Studio: Machine | Studio-Ablauf fertig (Simulation, §1.1); großer Start-Knopf der Hauptansicht ruft `one_click.start` (Canvas, §5.1); Maschinen-Panel erledigt (§1.2: „Auftrag starten“ → `op=autorun`, Service-Gruppe „Erweitert“, Phasenanzeige, alter Pi); Pi-Code fertig, auf dem Pi noch nicht installiert |
| Nullpunkt oben rechts | Canvas + Machine | Maschinenseite erledigt (`ce7da00`: Anker = sichtbare Ecke, `coord_convention`, Jog-Kreuz gespiegelt, siehe §2.2); Canvas (`workarea.py`, Absprache §2) offen |
| Kamera-Scan als Button | Scan Probe | Studio erledigt (§3); Android: Vertrag vorbereitet, kein Code |
| Probing immer im Auftrag (keine Auswahl) | Scan Probe | Studio erledigt (§1.1) |
| Materialdatenbank auf dem Pi | Pi-API `/api/materials`: **Claude, Session pi-automatik** (Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` Abschnitt 3); Anbindung in Studio: Materials | Studio-Client fertig (beide API-Varianten, offline, Konflikte; §4.1), Pi-Endpunkte in Arbeit |
| Cleaner UI Windows | Canvas | erledigt (`bc8092b` + Start → `one_click.start`, §5.1) |
| Cleaner UI Android | Claude, Session android | in Arbeit |

## 8. Nächste Schritte

1. Pi: Material-API und Speicherort definieren und dokumentieren.
2. Studio: Hauptansicht aufräumen, Start-Button macht den kompletten Ablauf.
3. Nullpunkt-Korrektur in Canvas und G-Code.
4. Android: gleiche Vereinfachung und Anbindung an die Pi-Materialdatenbank.
