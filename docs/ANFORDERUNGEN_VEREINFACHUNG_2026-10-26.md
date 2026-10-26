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

**Regel (Besitzer, 2026-10-26): Nicht erreichbare Abtastpunkte brechen den Auftrag nicht ab.** Kommt der Taster an einen geplanten Punkt nicht heran, wird stattdessen an der **nächstgelegenen erreichbaren Stelle** gemessen (Punkt in den Abtastbereich geklemmt, §2.4). Der Punkt gilt im Höhenmesh als **„ersetzt/Nachbarmessung“**, es gibt eine **Warnung** (welche Seite, wie viele mm, Gefahrenhinweis), und **gelasert wird trotzdem**. Fehler bleiben nur: Taster misst gar nicht / kein Material gefunden, Not-Aus, Abbruch.

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

- Ein Startknopf: der große **„Start“** der Hauptansicht (`one_click.start`). Der
  Panel-Knopf unter „Mehr › Maschine“ heißt seit 2026-10-26 **„Datei-Auftrag starten“**
  (nicht mehr hervorgehoben; sendet eine gewählte Datei im selben Klick, dann
  `op=autorun`, mit Platzierung `placement=1` falls gewählt). Kein Probing-Schalter,
  keine Referenzfahrt aus Studio.
- Home, Park, Fokus (G30), Jog, Notstopp quittieren und „Ohne Automatik starten“
  (`op=start`) liegen in der eingeklappten Gruppe **„Erweitert: Bewegung, Taster, Jog“**.
- Phasenanzeige aus `/api/status`, abgeglichen mit `web.py`: `job.state`
  homing/probing/running/complete/aborted/error, `job.probe` = „Abtasten 3 / 13“. Der Pi
  sendet kein `job.phase`; „Parken“ zeigt das Panel, wenn `state=running` und
  `line == total` (Pi leert den Puffer und parkt). Fokus ist Teil von Abtasten/Laufen.
  Ein künftiges `job.phase` hat Vorrang. Abbrechen und NOT-AUS in jeder Phase.
- Pi ohne Merkmal `autorun_mesh` (`features`): Tooltip und Rückfrage sagen „tastet nur
  einen Punkt ab – Pi aktualisieren“.
- `MachinePanel.autorun_task(name)` (GUI-Thread aufrufen, Ergebnis im Worker ausführen):
  platziert nach gewähltem Ursprung/Bezugspunkt und startet `op=autorun placement=1`.
  Damit kann `OneClickController` mit `autorun_mesh` auch platzierte Aufträge starten
  (heute lehnt er Ursprung ≠ „Absolut“ ab; Übergabe an Scan Probe, §1.3).
  `send_gcode(..., autorun=True)` folgt jetzt ebenfalls dem gewählten Ursprung.
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

### 1.3 Lückenprüfung Ein-Klick-Ablauf (Machine-Agent, 2026-10-26)

Ablauf Material → Design → Start → Referenzfahrt → Abtasten → Fokus → Auftrag → Parken.
Geprüft gegen `pi400/marlin/web.py`, `scanprobe/job_flow*.py`, `main_view.py`, `main.py`.

| Punkt | Stand | Offen bei |
|---|---|---|
| Ein Startknopf | Hauptansicht „Start“ → `one_click.start`; Panel-Knopf umbenannt („Datei-Auftrag starten“). Unter „Mehr“ bleiben „Hochgeladenen Auftrag starten“ (`op=start`) und „Ohne Automatik starten“ für Fachleute | – |
| Eine Phasenanzeige | Während des Ein-Klick-Ablaufs sperrt `set_external_operation` die Panel-Knöpfe (auch Panel-„Abbrechen“); Abbruch über „■ Abbrechen“ der Hauptansicht, NOT-AUS (Toolbar + Panel) bleibt aktiv. Panel-Phasenzeile und Scan-Probe-Anzeige lesen dieselben `job.*`-Felder | Erledigt: Panel „Letzte Bahnen, dann Parken“ (`finishing`), Hauptansicht-Text in `scanprobe/job_flow.py:625` angeglichen (Einzeiler, Machine-Agent) |
| Platzierung + Mesh | Pi kann `autorun placement=1` (Raster über dem platzierten Auftrag); `OneClickController.start()` nutzt bei `autorun_mesh` `machine_panel.autorun_task(name)` (Scan Probe `d7e1fe2`), ohne Merkmal klare Meldung | – |
| Alter Pi | ohne `autorun`: klare Meldung; ohne `autorun_mesh`: Hinweis „ein Punkt“; ohne `coord_convention`: `wire_anchor` tauscht links/rechts (Test `test_origin_end_to_end.py`) | Studio und Pi gemeinsam aktualisieren |
| Warteschlange | `_queue_worker` startet ohne `auto` → kein Abtasten/Fokus, verlangt Referenzfahrt. Studio sagt das jetzt im Tooltip und in der Rückfrage (`QUEUE_NOTE`); `fake_pi` verlangt wie der Pi Referenzfahrt für `start`/`queue_run` | Claude: Warteschlange über den Autorun-Ablauf (ZUSAMMENARBEIT §6) |
| Parken | Pi parkt nach jedem Auftrag selbst (`park_safezone`) | – |
| Fehler/Abbruch je Phase | Pi setzt `aborted`/`error` + `job.error`, Panel zeigt den Satz (Test `test_pi_error_texts_shown`); Abtasten prüft `stop_job` vor jedem Punkt, Laufen vor jeder Zeile; NOT-AUS = M112 in jeder Phase. `safe_home` prüft `stop_job` nicht: Abbruch während Referenzfahrt wirkt erst danach | Claude: Referenzfahrt abbrechbar machen; ⚠ am Gerät: Abbruch während Abtasten |
| Veralteter Status | `stale_ms`/`pi_busy` sperren Knöpfe, NOT-AUS bleibt | – |
| Schließen während Auftrag | `confirm_close` fragt nach | – |
| Workflow-Senden | `lumacut_workflow/qt.py:166` ruft `send_gcode(..., start=True)` (ohne Automatik). Kein Einzeiler: `lumacut_job/history_qt.py:41` umhüllt `send_gcode(name, gcode, start=False)` und würde bei `autorun=True` mit TypeError scheitern | **Job-Besitzer:** Hülle in `history_qt.py:41` um `autorun`/`**kw` erweitern; danach **Workflow:** `autorun=True` in `qt.py:166` |
| Mehrfach-Durchgänge mit relativem Z | Geklärt im Code: `focus_compensation.compensate` rechnet die relativen Absenkungen nur bei `op=autorun` (ohne eigenes absolutes Z) in die Karten-Höhe ein (max. 20 mm, nie unter Oberfläche + 2 mm, sonst Fehler „Fokus-Absenkung führt unter Oberfläche + 2 mm“). Bei `op=start`, Warteschlange und Aufträgen mit eigenem Z gehen sie roh an Marlin | Claude: bestätigen, dass das so gewollt ist (§6) |
| Nullpunkt §2.3 | Erledigt: Canvas `ORIGIN_TOP_RIGHT = True` (`workarea.py:53`, `3b79ab6`), Scan Probe `f00485e`/`d8b4528`; `test_visible_top_right_is_near_switch_corner` läuft jetzt mit | – (⚠ am Gerät) |
| ⚠ Hardware | Jog-Richtungen (X+ links, Y+ zur Tür), Lage des Testrechtecks, Abtastraster am Gerät | Nutzer am Gerät |

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

### 2.3 Umsetzung Canvas (Studio Windows, 2026-10-26)

**Status: auf `main` (`3b79ab6`, Schalter an; Helfer `c75182b`).** Gepusht nach dem Scan-Probe-Teil (`f00485e`, `3c3a801`, `d8b4528`); volle Studio-Suite grün. Raster: Bildspalte 0 liegt bei `390 − x` (großes Maschinen-X), Test `test_origin_top_right.py::test_raster_column_0_lands_at_large_machine_x`. Der Kamera-Scan-Knopf der Hauptansicht ruft jetzt `ScanPanel.camera_scan()`.

**Ein Schalter, eine Stelle (`lumacut_canvas/workarea.py`):**
- `ORIGIN_TOP_RIGHT = True` ist der einzige Schalter.
- Umgerechnet wird nur hier, mit drei Koordinatenarten:
  - **Bildschirm** (Dokument, Szene, Overlays, SVG/PNG): oben links, x nach rechts, wie bisher.
    - Die Szene wird **nicht** gespiegelt (kein `scale(-1, 1)`), Text und Bilder bleiben lesbar.
  - **Anzeige** (Lineale, Statusleiste, X/Y-Felder, Gitterbeschriftung): Nullpunkt oben rechts, X nach links.
    - Umrechnung mit `screen_to_user(x, y) = (360 − x, y)`.
    - Das X-Feld zeigt den Abstand der **rechten** Kante vom Nullpunkt.
    - Breite/Höhe ändern hält die Nullpunkt-Seite fest. Am linken Rand wird die ganze Auswahl gemeinsam zurückgeschoben.
  - **Maschine** (G-Code, Rahmen, Schätzung, Raster, Bilder, Relief): `screen_to_machine(x, y) = (390 − x, 30 + y)`, wie in §2.1.
    - `to_machine`/`from_machine` bleiben als Namen und nehmen **Bildschirm**-mm.
    - Hinweis zu §2.2: Dort steht `(u + 30, v + 30)` für **Anzeige**-Koordinaten u/v. Das ist dieselbe Umrechnung.
- Grenzen des Schneidbereichs: `MACHINE_X_MIN/MAX`, `MACHINE_Y_MIN/MAX` = 30/390, 30/370. Diese Konstanten nutzen gcode, estimate, raster, cutpath und relief statt eigener Rechnungen.
- Bilder: `IMAGE_FLIP_X`. Rasterzeilen laufen in Maschinenrichtung, der Ursprung ist `to_machine(rechte Kante, oben)`.

**Dateien:**
- Gespeichert wird weiter in Bildschirm-mm. Alte `.lumacut.json` liegen deshalb an **derselben sichtbaren Stelle**, ohne Umrechnung.
- Neu ist das Feld `"coords": "screen-tl/machine-tr-v2"`.
  - Fehlt es, ist die Datei alt, und das ist in Ordnung.
  - Ein unbekannter Wert wird abgelehnt.
  - `VERSION` bleibt gleich, damit ältere Studios die Dateien weiter öffnen.
- Achtung: Ein alter Auftrag kommt auf der Maschine jetzt **an der gespiegelten Stelle** heraus, und zwar richtig herum. Vorher kam er seitenverkehrt.

**Tests:** `tests/test_origin_top_right.py` prüft:
- Formel, Ecken und Hin- und Rückweg.
- +X = nach links.
- Eine Form links ergibt großes Maschinen-X, nicht gespiegelt.
- Anzeige- und X-Feld-Werte.
- Alte Datei an derselben Stelle; unbekannte Konvention wird abgelehnt.

Die Canvas-Tests (G-Code, Drehung, Import/Rahmen, Eigenschaftsleiste, Statusleiste) sind auf die neue Abbildung umgestellt.

**Was Scan Probe spiegeln muss (`scanprobe/panel.py`):**

Platzierung (Vektoren) und Bilder (Mosaik, Höhenkarte) sind getrennt zu behandeln:

1. **Platzierung, Rechtecke aus zwei Ecken:** Über `to_machine` entstehen jetzt `x0 > x1`.
   - Betroffen sind `work_rect_machine()` sowie die Design-Boxen (`Rect(x0, y0, x1, y1)`, ca. Z. 844) und der ROI (ca. Z. 890).
   - Die Ecken müssen mit `min`/`max` sortiert werden, sonst kommt `ValueError: Rect max must be >= min`.
   - Polygone und Punkte über `to_machine`/`from_machine` stimmen bereits.
2. **Rückfall ohne Canvas-Paket:** `to_machine = (390 − x, y + 30)` und `from_machine = (390 − x, y − 30)`.
3. **Bilder:** In `mosaic_to_work_image()` und beim Höhenkarten-Bild (`heatmap_rgba` in `set_heatmap`) ist Spalte 0 das kleinste Maschinen-X. Auf dem Bildschirm liegt das jetzt **rechts**.
   - Beide Bilder bei `IMAGE_FLIP_X` waagerecht spiegeln (`img[:, ::-1]`).
   - Alternative: `machine_rect_to_screen()` für Lage und Ausdehnung nutzen.
   - Die Beschriftung erkannter Objekte gehört an `bounds.xmax` (linke Bildschirmkante).
4. **Scan-Tests:** Mehrere Tests legen Canvas-Formen und Fake-Mesh mit `Maschine = Bildschirm + 30` übereinander, etwa `test_focus_export._union_mesh_rect` und die Szenen in `test_scan_panel`/`test_scan_marking`/`test_workflow`. Diese Tests müssen auf `to_machine` bzw. `390 − x` umgestellt werden.
- Ein Patchvorschlag für 1–3 liegt auf der Box unter `/workspace/origin-scanprobe.patch` (nicht committet). Damit sinken die Fehler von 31 auf 17, und alle verbleibenden 17 liegen an Punkt 4.

**Machine:** Keine Codeänderung nötig. Anker `tr` = Nullpunkt-Ecke passt (§2.2).

**Scan Probe: erledigt (`f00485e`, `3c3a801`; Scan Probe, 2026-10-26).** Canvas kann 23b8d56 pushen.
- Punkte 1–4 umgesetzt. `scanprobe/panel.py` leitet die Spiegelung aus `to_machine` ab (`image_flip_x()`), ohne eigenen Schalter. Das gilt mit `ORIGIN_TOP_RIGHT` an und aus.
- Doppelter „Kamera-Scan“-Knopf im Scan-Panel entfernt, `start_scan()` bleibt. Den Wechsel auf den Pi bei bestehender Verbindung macht nur `camera_scan()`. Die Hauptansicht sollte daher `camera_scan()` statt `start_scan()` aufrufen.
- Tests: `tests/test_scan_origin_top_right.py` prüft den Hin- und Rückweg Maschine ↔ Bildschirm, die Rechtecke und Umrisse, ob Mosaik und Höhenkarte deckungsgleich liegen, und die Export-Abdeckung. Die Hilfen dazu liegen in `tests/scan_coords.py`. Die Studio-Suite ist grün ohne den Canvas-Patch und mit ihm (offscreen, Simulation, ohne Hardware).
- Vertrag wie `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` §2 und Android `Work.toMachine/fromMachine`: `maschine = (390 − x, 30 + y)`, `x = 390 − maschine_x`, `y = maschine_y − 30`. Die Tests (`d8b4528`) prüfen genau diese Formeln, auch für den Rückfall ohne Canvas-Paket. Zusätzlich prüfen sie, dass Bildschirmspalte 0 des Mosaiks bei Maschinen-X 390 liegt.
- **Abweichung in der Wortwahl:** Oben (Punkt 3, Canvas-Patch `IMAGE_FLIP_X`) steht „waagerecht spiegeln“, der Vertrag sagt „Drehung, keine Spiegelung“. Es gilt der Vertrag. Für Scan Probe ist das kein Rechenunterschied. Mosaik und Höhenkarte liegen als Maschinen-Raster vor (Spalte 0 = Maschinen-X 0). Die umgekehrte Spaltenfolge ist nur die Bildform von `x = 390 − maschine_x`; das Motiv erscheint so, wie man es von der Tür aus sieht. Canvas sollte beim Rastern prüfen, dass Bildspalte 0 bei `390 − x` (großes Maschinen-X) liegt, wie im Vertrag.

**Physische Prüfung (⚠ offen):** Nach dem Homing in der Studio-Ansicht prüfen:
- **X+10 fährt den Kopf nach links**, **Y+10 nach vorne zur Tür**.
- Ein Testrechteck **oben links** auf dem Bildschirm wird **vorne gesehen oben links** gelasert, und Text ist lesbar.

### 2.4 Abtastbereich / Erreichbarkeit (Scan Probe, 2026-10-26)

**Anlass:** Der Pi meldete „Kein Abtastpunkt erreichbar: der Taster kommt an keine Stelle des Motivs – Motiv weiter in die Mitte schieben, dann neu starten.“ (HTTP 400). Das Motiv lag unten links auf dem Bildschirm.

**Rechnung (Maschinenkoordinaten, ohne Bildschirm-Konvention):**
- Versatz `d = Tasterspitze − Laser` (Pi: `machine.probe_xy_offset_mm`, eingetragen −23/+15). Kopf beim Abtasten = Laserpunkt − d.
- Pi `transport.py:1075` `_probe_head_ok`: `safe_zone (30) ≤ Kopf-X ≤ 380` und `30 ≤ Kopf-Y ≤ 360` (`PROBE_HEAD_MAX`, Marlin PROBING_MARGIN 10 mm). Firmware `NOZZLE_TO_PROBE_OFFSET {0,0,0}` (`firmware/marlin/build.py:98`), der Pi rechnet den Versatz selbst.
- Erreichbare Laserpunkte: X `30+dx … 380+dx`, Y `30+dy … 360+dy` → mit −23/+15: X 7–357, Y 45–375; geschnitten mit dem Arbeitsbereich X30–390/Y30–370: **Maschine X30–357, Y45–370**.
- Bildschirm (`x = 390 − X`, `y = Y − 30`): **x 33–360 mm, y 15–340 mm**. Nicht abtastbar: **linker Rand 33 mm** (Maschine X > 357) und **oberer Rand 15 mm** (Maschine Y < 45, hinten).

**Urteil:** Die Pi-Prüfung rechnet richtig (kein Spiegelfehler durch Nullpunkt oben rechts). Ein Motiv in den linken 33 mm des Bildschirms ist mit dem eingetragenen Versatz wirklich nicht abtastbar.
- ⚠ Hardware offen: Das Vorzeichen des Versatzes −23/+15 wurde am 25.10. vor der neuen Konvention eingetragen. Prüfen: Laserpunkt schießen, Tasterspitze darüberfahren, Versatz = Punkt − Kopfposition. Ist das Vorzeichen falsch, liegt der nicht abtastbare Streifen rechts/unten statt links/oben.
- ⚠ Kopf-Y min 30 (safe zone) kostet oben 15 mm; Marlin erlaubt 10. Lockern nur nach Prüfung am Gerät (Claude).
- Studio-Fehler (behoben, Scan Probe): `scanprobe/probe_plan.grid_for_area` prüfte nur 0–390/0–370 statt der Pi-Kopfgrenzen; der Pi hätte solche Punkte mit „Werkstück-Abtastpunkt außerhalb“ abgelehnt. Jetzt `MachineLimits.probe_head_ok` wie der Pi.

**Neue Regel (Besitzer, 2026-10-26) – kein Abbruch, Ersatzpunkt:**
1. Ist ein geplanter Abtastpunkt nicht erreichbar, wird er auf den nächsten erreichbaren Punkt geklemmt: `X' = min(max(X, Xmin), Xmax)`, `Y'` ebenso (Bereich oben). Gemessen wird bei (X', Y'); der Wert gilt für den Originalpunkt.
2. Im Höhenmesh wird der Punkt als **„ersetzt/Nachbarmessung“** markiert (Statistik + eigenes Symbol in der Heatmap), mit Abstand in mm.
3. Warnung (ein Satz, gleicher Wortlaut Studio/Pi/Android), z. B.: „Achtung: 3 Abtastpunkte am linken Rand (Maschine X > 357) nicht erreichbar – stattdessen bis 12 mm daneben gemessen. Ist das Werkstück dort kleiner, landet der Taster neben dem Werkstück auf dem Bett und die Höhe stimmt am Rand nicht. Gelasert wird trotzdem.“
4. Der Auftrag läuft weiter (Laser startet). Fehler bleiben: Taster misst gar nicht / kein Material, Not-Aus, Abbruch.
5. Studio-Vorprüfung vor dem Hochladen: gleiche Rechnung wie der Pi, Ergebnis jetzt **Warnung** in Bestätigung und Status, kein Fehler.

**Übergaben:**
- **Claude (Pi):** `heightmap._mark_reachable` (`pi400/marlin/heightmap.py:271–278`) wirft den 400er; stattdessen klemmen und weitermachen, Warnungsliste in Antwort und `job.probe.warnings` (Details `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` §6). Zusätzlich Abtastbereich in `/api/status` melden (`probe_reach_mm: [xmin, ymin, xmax, ymax]`).
- **Claude (Android):** Warnung anzeigen, kein Abbruch, gleicher Wortlaut (Pi-Vertrag).
- **Canvas (Vorschlag, kein Code von Scan Probe):** Abtastbereich als gestrichelte Fläche einblenden (Bildschirm x 33–360, y 15–340 beim Standardversatz; `scanprobe.reach.screen_box(work_reach(offset))`), Rand außerhalb leicht schraffiert „hier wird daneben gemessen“.
- **Machine:** keine Code-Änderung nötig; platzierte Aufträge (`autorun_task`) zeigen die Warnung des Pi.

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

### 4.1 Umsetzung Windows-Studio (Materials-Agent) – gegen den echten Pi geprüft (2026-10-26)

Pi-Dienst: `pi400/marlin/materials.py` + Routen in `web.py` (Claude, pi-automatik;
`docs/PI_API_REFERENZ.md` §4.14, Vertrag `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` §3).
Der Pi spricht **Variante B – eine flache Materialliste mit Revision**, gespeichert in
`/var/lib/lumacut/materials.json` (atomar):

| Anfrage | Antwort |
|---|---|
| `GET /api/materials` | `{"revision": n, "materials": [Material]}` (beim ersten Start 7 Startwerte, `builtin: true`, Revision 1) |
| `POST /api/materials` (Material ohne `id` + `base_revision`) | `{"revision": n+1, "material": …}`, `id` = UUID vom Pi |
| `PUT /api/materials/<id>` (geänderte Felder + `base_revision`) | `{"revision": n+1, "material": …}`; fehlende Felder bleiben |
| `DELETE /api/materials/<id>?base_revision=n` | `{"revision": n+1}` |
| Fehler | 409 `{"error", "revision"}` (veraltete Revision, wird *vor* 404/400 geprüft), 404 `{"error": "Material nicht gefunden"}`, 400 `{"error": …}` (Bereich, `null`, `base_revision` fehlt) |

Kein ETag/304, keine vollständige Datenbank auf dem Pi. **Unbekannte Felder bleiben
erhalten** (≤ 32 Felder, ≤ 16 KB), auch wenn Android per PUT nur die Pi-Felder schickt.
Bereiche: Leistung 0–100 %, Tempo 1–6000 mm/min, Durchgänge 1–30, Zeilenabstand
0,01–5 mm (Standard 0,1), Z-Schritt 0–2 mm, Dicke/Tiefe ergibt höchstens 30 Durchgänge,
gesamte Z-Absenkung höchstens 3 mm, Name 1–80 Zeichen.

Studio (`src/lumacut_materials/remote.py`, `sync.py`, Anbindung in `dialog.py`):
- **Beim Verbinden** gleicht Studio im Hintergrund ab (auch Menü *Material → Materialdatenbank
  vom Pi laden*). Jeder Pi-Eintrag ist ein Preset unter „Eigene Presets“ und im Ebenen-Panel;
  gleiche Namen (z. B. Pappelsperrholz schneiden/gravieren) bekommen die Operation angehängt.
  Planungswerte (Laser, Modell, Material-Auswahl) kommen weiter aus der mitgelieferten Datenbank.
- **Speichern** (Preset, Testzelle) geht bei Verbindung sofort auf den Pi, sonst lokal und
  beim nächsten Verbinden automatisch hoch; Löschen genauso.
- **Abbildung** Preset ↔ Material: `op=cut` ↔ `Schneiden/line`, `engrave_surface` ↔
  `Markieren/fill`, andere Gravuren ↔ `Gravieren/fill`, `line_interval_mm` ↔ `interval_mm`.
  Studio schickt `material_id`, `op`, `laser_id`, `air_assist`, `focus_start_mm`, `notes`,
  `warnings`, `source` mit. Ändert Android/Pi-Web `process`, gilt `process` (nicht das alte `op`).
  Werte werden auf die Pi-Bereiche begrenzt (z. B. 12000 → 6000 mm/min, wie die Ebene ohnehin fährt),
  leere Werte weggelassen.
- **Konflikte**: veraltete Revision durch Änderungen an *anderen* Einträgen → still mit neuer
  Revision wiederholt. Derselbe Eintrag auf dem Pi geändert/gelöscht → Frage „meine Fassung /
  Fassung vom Pi“. Offline geändert *und* auf dem Pi geändert → Pi gewinnt, eigene Fassung
  bleibt als „<Name> (lokal)“.
- **Vom Pi abgelehnt** (400, z. B. > 30 Durchgänge): Preset bleibt lokal und ausstehend,
  Studio zeigt den Grund, der übrige Abgleich läuft weiter.
- **Ohne Pi / alter Pi (404)**: lokale Presets + mitgelieferte `materials.json`, Warteschlange
  wird beim nächsten Verbinden abgearbeitet.

**Geprüft** (`software/lumacut-studio-native/tests/test_materials_pi_real.py`): der echte
`web.py`-Dienst läuft im Testprozess (Temp-Daten über `LUMACUT_DATA`, ohne Hardware), zwei
Studio-Geräte dagegen: Erstabgleich der 7 Startwerte (zweiter Abgleich ohne Änderung),
Speichern mit Studio-Zusatzfeldern und Unicode, Ändern (PUT, gleiche ID), Änderung wie von
Android, Löschen, Revisionskonflikte (still / meine / Pi / gelöscht), Offline-Warteschlange
(neu, geändert, gelöscht) inkl. „(lokal)“-Kopie, Werte außerhalb der Bereiche, 400-Ablehnung,
alter Pi (echte Flask-404), 300 Einträge mit Umlauten/€ (< 10 s). Ergebnis: alle grün
(Studio 766 + neue, Wurzel 166). Dabei gefunden und behoben: Schreiben vor dem ersten Abgleich
ging an die falsche URL (nur lokal gespeichert); `interval_mm = 0`/`null` und Tempo > 6000
wurden abgelehnt und brachen den ganzen Abgleich ab; doppelte Namen der Startwerte.
`tests/fake_materials_pi.py` (Variante „list“) prüft jetzt wie der Pi.

Offen:
- Die eingebaute Studio-Datenbank (Materialien, Laser, Planungsmodell) bleibt lokal und nur
  lesbar; geteilt werden die Einstellungs-Einträge. Die Pi-Startwerte (`builtin`) sind
  wie eigene Einträge änderbar/löschbar.
- Android legt Einträge ohne Studio-Felder an → Studio ordnet sie über `process` zu
  (`material_id`/`laser_id` leer, Planung im Dialog dann manuell).
- Pi-Web-UI (`index.html`) nutzt `/api/materials` noch nicht.
- Studio liest neu nur beim Verbinden/Menü, nicht laufend (kein Push vom Pi).
- Variante A (`/api/materials/presets`, ETag) bleibt im Client als Rückfall, der Pi bietet sie nicht.

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
| Ein-Klick-Auftrag (Homing + Probing + Fokus + Job) | Pi-Ablauf (`op=autorun`, Abtastraster, Höhenkorrektur auf dem Pi): **Claude, Session pi-automatik**; Studio-Ablauf/Orchestrierung: Scan Probe; Start-Knopf in Studio: Machine | Studio-Ablauf fertig (Simulation, §1.1); großer Start-Knopf der Hauptansicht ruft `one_click.start` (Canvas, §5.1); Maschinen-Panel erledigt (§1.2: „Datei-Auftrag starten“ → `op=autorun`, Service-Gruppe „Erweitert“, Phasenanzeige mit echten Pi-Feldern inkl. „Letzte Bahnen, dann Parken“, Hinweis ohne `autorun_mesh`, `autorun_task` für platzierte Ein-Klick-Aufträge, Warteschlangen-Hinweis); Studio gegen `web.py` abgeglichen (§1.3, ZUSAMMENARBEIT §6). Platzierte Aufträge über `autorun_task` (Scan Probe `d7e1fe2`). **Offen:** Job-Besitzer `history_qt.py:41` + Workflow `qt.py:166` (`autorun=True`), Claude-Wünsche §6, Entscheidung Zusatz-Startknöpfe unter „Mehr“ (Nutzer); Pi-Code fertig, auf dem Pi noch nicht installiert |
| Nullpunkt oben rechts | Canvas + Machine + Scan Probe | Software erledigt: Maschinenseite (`ce7da00`, §2.2), Scan Probe (`f00485e`, `3c3a801`, `d8b4528`, §2.3), Canvas `ORIGIN_TOP_RIGHT` (`3b79ab6`); Ende-zu-Ende-Test `tests/test_origin_end_to_end.py` läuft vollständig. Offen: physische Prüfung am Gerät |
| Kamera-Scan als Button | Scan Probe | Studio erledigt (§3): Hauptansicht → `camera_scan` (verbundener Pi = echter Scan, sonst Simulation), Sperre mit deutschem Satz bei Platzhalter-Kalibrierung, fehlendem Home oder G30, Leerbett-Referenz unter „Mehr …“ (`16a848a`). ⚠ echter Scan, Kalibrierung und Erkennung nur am Gerät prüfbar. Android: kein Code nötig, App scannt selbst und nutzt Pi-Vertrag §4 (`docs/SCAN_PROBE.md` §3) |
| Probing immer im Auftrag (keine Auswahl) | Scan Probe | Studio erledigt (§1.1): grobes Raster + adaptiv, Mesh-Wiederverwendung, Bereiche aus der Brennstrecke; braucht keine Kamera-Kalibrierung (`d7e1fe2`). ⚠ G30-Reichweite und Abbruch während des Abtastens nur am Gerät prüfbar |
| Materialdatenbank auf dem Pi | Pi-API `/api/materials`: **Claude, Session pi-automatik** (Vertrag: `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` Abschnitt 3); Anbindung in Studio: Materials | Pi-API fertig (Variante B, Revision); Studio gegen den echten Pi-Dienst geprüft (§4.1); Android angebunden; Pi-Web offen |
| Cleaner UI Windows | Canvas | erledigt (`bc8092b` + Start → `one_click.start`, §5.1) |
| Cleaner UI Android | Claude, Session android | in Arbeit |

## 8. Nächste Schritte

1. Pi: Material-API und Speicherort definieren und dokumentieren.
2. Studio: Hauptansicht aufräumen, Start-Button macht den kompletten Ablauf.
3. Nullpunkt-Korrektur in Canvas und G-Code.
4. Android: gleiche Vereinfachung und Anbindung an die Pi-Materialdatenbank.
