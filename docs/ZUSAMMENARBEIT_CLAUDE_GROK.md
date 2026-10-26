# Zusammenarbeit Claude und Grok – Vereinfachung 2026-10-26

Auftrag des Besitzers (gleicher Text an Claude und Grok): Windows-App und Android-App
so vereinfachen, dass auch ein Neuling damit klarkommt. Material wählen → Motiv drauf
und bearbeiten → **Auftrag starten**. Alles andere passiert automatisch. Dieses Dokument
ist die **einzige verbindliche Absprache** zwischen den Agenten. Wer etwas am Vertrag
(Abschnitte 2–5) ändern muss, ändert zuerst dieses Dokument (eigener Commit, Eintrag im
Änderungslog unten) und erst dann den Code.

## 1. Zuständigkeiten (wer schreibt welche Dateien)

| Bereich | Dateien | Zuständig |
|---|---|---|
| Pi-Dienst: Material-Datenbank, automatischer Auftrag, schnelles Abtasten, Höhenkorrektur auf dem Pi | neue Module in `pi400/marlin/` (z. B. `materials.py`, `autojob.py`, `focus_mesh.py`) plus kleine Einhängepunkte in `web.py`/`transport.py`, `firmware/marlin/`, `tests/test_marlin_gateway.py`, neue Tests unter `tests/`, API-Abschnitte für Material und Auftrag in `docs/PI_API_REFERENZ.md` | **Claude** (Agent „Pi-Automatik“) |
| Android-App | `android/**`, `docs/ANDROID_APP.md`, `.github/workflows/android.yml` | **Claude** (Agent „Android“) |
| Windows-App | `software/lumacut-studio-native/**` | **Grok** |
| Web-Oberfläche des Pi | `pi400/marlin/index.html`, `tests/ui_mock_server.py`, `docs/PI_WEB_UI_REDESIGN.md` | **Grok** |
| Platzierungsanker, Studio-Maschinenseite | `pi400/marlin/placement.py`, `software/lumacut-studio-native/src/machine/` | **Grok** (Machine-Agent) |
| Diese Absprache | `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` | beide, nur Abschnitt 6 frei; Abschnitte 2–5 nur mit Änderungslog |

Regeln:
- Fremde Dateien nicht anfassen. Braucht man dort etwas, Wunsch in Abschnitt 6 eintragen.
- Vor jedem Commit `git fetch` + Rebase/Merge auf `origin/main`, kleine Commits, Commit-Text
  sagt was und warum. Nie `--force`, nie fremde Commits zurücksetzen.
- Gearbeitet wird auf `main` (Wunsch des Besitzers). Größere Umbauten dürfen über einen
  Feature-Branch laufen, der vor dem Merge auf `main` grün getestet ist.
- Nichts flashen und keine Maschinenbewegung ohne den Besitzer.

## 2. Koordinaten (ab jetzt für alle Programme)

Der Besitzer steht an der Tür, die **Endschalter-Ecke (Maschine X0/Y0) ist von dort aus
hinten rechts**. X+ fährt nach links, Y+ zur Tür. Alle Programme zeigen die Maschine so,
wie man sie von der Tür aus sieht:

- Bildschirm/Arbeitsbereich: 360 × 340 mm, Nullpunkt **oben links**, x nach rechts, y nach unten.
- Die 30-mm-Safezone (Maschine X < 30 oder Y < 30) liegt damit **oben und rechts** und ist unsichtbar.
- **Umrechnung (einzige Stelle je Programm):**
  - `maschine_x = 390 − x`, `maschine_y = 30 + y`
  - `x = 390 − maschine_x`, `y = maschine_y − 30`
- Das ist eine Drehung um 180° gegenüber der Standardansicht, **keine Spiegelung**: Text
  wird lesbar gelasert. Die bisherige Umrechnung `maschine = x + 30` hat in X gespiegelt
  und muss in beiden Apps ersetzt werden (Android `Work.toMachine/fromMachine`, Windows
  `lumacut_canvas/workarea.py: to_machine/from_machine`).
- Rasterbilder: Bildzeile 0 liegt oben auf dem Bildschirm (kleinstes y, Maschine Y 30).
  Bildspalte 0 liegt links auf dem Bildschirm, also bei **großem** Maschinen-X (390 − x).
  Beim Rastern laufen die Spalten deshalb in Maschinen-X rückwärts.
- Der Pi rechnet weiter nur in Maschinenkoordinaten; an seiner API ändert sich nichts.
- Einzige Ausnahme (Grok, Machine-Agent, `placement.py`): Die Platzierungsanker von
  `op=place` / `op=queue_add` (`anchor`) benennen ab jetzt die **sichtbare Ecke** von der Tür
  aus: `tr` = Endschalter-Ecke (kleinstes Maschinen-X/Y, neuer Standard), `tl` = größtes X,
  `br`/`bl` entsprechend zur Tür hin. Der Pi meldet das in `/api/status` als
  `coord_convention: "origin_top_right"`; fehlt das Feld (alter Pi), tauschen Clients
  links/rechts. Koordinaten selbst (`x`/`y`, `set_user_origin`) bleiben Maschinen-mm.
  Android nutzt keine Anker und ist nicht betroffen.

## 3. Material-Datenbank auf dem Pi (neu, Claude baut, alle nutzen)

Eine Liste für alle Programme, gespeichert auf dem Pi (`/var/lib/lumacut/materials.json`,
atomar geschrieben, mit Revision gegen gleichzeitiges Ändern).

```
GET    /api/materials                 -> {"revision": 7, "materials": [Material, ...]}
POST   /api/materials                 Body: Material ohne id, "base_revision"  -> {"revision": 8, "material": Material}
PUT    /api/materials/<id>            Body: Material, "base_revision"          -> {"revision": 9, "material": Material}
DELETE /api/materials/<id>?base_revision=9                                      -> {"revision": 10}
409 {"error": "...", "revision": n}   wenn base_revision veraltet ist (neu laden, erneut versuchen)
```

Material (JSON, Einheiten im Namen):

```
{ "id": "uuid", "name": "Pappel-Sperrholz", "thickness_mm": 3.0,
  "process": "Schneiden" | "Gravieren" | "Markieren",
  "mode": "line" | "fill", "power_pct": 80.0, "speed_mm_min": 400.0,
  "passes": 2, "interval_mm": 0.1, "depth_per_pass_mm": 0.0, "z_step_mm": 0.5,
  "builtin": false, "updated": "2026-10-26T15:00:00Z" }
```

Grenzen wie bisher: Leistung 0–100 %, Tempo 1–6000 mm/min, Durchgänge 1–30,
Z-Absenkung 0–2 mm und gesamt ≤ 3 mm. Beim ersten Start legt der Pi die Startwerte an.
Die Apps halten nur einen Zwischenspeicher für den Fall ohne Verbindung.

## 4. Automatischer Auftrag (neu, Claude baut, alle nutzen)

Die Apps schicken nur noch den fertigen Auftrag (Maschinenkoordinaten, ohne Z) und
drücken „Starten“. Der Pi erledigt den Rest:

```
POST /api/upload  (file)                       wie bisher
POST /api/action  op=autorun  name=<datei>     startet den automatischen Ablauf
```

Ablauf auf dem Pi, ohne Rückfragen:
1. Referenzieren, **nur wenn nötig** (nicht referenziert oder nach Not-Aus/Reset).
2. **Abtasten automatisch** über den Flächen, auf denen gelasert wird: kleines Raster
   je Motivbereich (Anzahl Punkte aus der Größe, Ziel: schnell), Punkte, die der Taster
   nicht erreicht, aus Nachbarn ergänzt, tiefster Punkt zuletzt.
   Schnell heißt: niedriger Zwischenhub zwischen den Punkten, eine Messung pro Punkt.
3. Höhenkorrektur auf dem Pi (Fokus folgt der Oberfläche, wie bisher in den Apps).
4. Lasern, danach Parken, Melodie.

Fortschritt in `/api/status` → `job`: `state` = `homing` | `probing` | `running` |
`complete` | `error`, dazu `probe: {"done": 3, "total": 12}` während des Abtastens.
Die bisherigen Felder bleiben, `op=start` (ohne Abtasten) bleibt für Fachleute.

## 5. Bedienkonzept (beide Apps gleich)

Hauptweg, drei Schritte, immer sichtbar:
1. **Material** wählen (Liste vom Pi, mit Suche).
2. **Motiv**: importieren (Bild, SVG, DXF), Text, Formen; verschieben, drehen, skalieren.
3. **Starten**: ein Knopf. Davor eine kurze Zusammenfassung (Dauer, Material, Größe) und
   „Rahmen zeigen“ als optionaler Knopf. Dann läuft Abschnitt 4.

- **Arbeitsplatz scannen** ist ein einzelner Knopf (optional), der Ergebnisbild als
  Hintergrund legt. Kalibrierung liegt in den Einstellungen.
- Alles Weitere (Ebenen-Details, Leistung pro Ebene, Jog, Taster, Firmware) steckt unter
  **„Erweitert“** bzw. in einer eigenen Seite „Maschine“. Ein Neuling braucht es nie.
- Keine Entscheidungen „mit/ohne Höhenkarte“, „Referenzieren“ oder „Abtasten“ im Hauptweg.
- Fehlermeldungen in einem Satz mit dem nächsten Schritt.

## 6. Offene Wünsche und Fragen (frei für beide)

- (Claude) Grok: bitte `to_machine/from_machine` in der Windows-App auf Abschnitt 2 umstellen
  und den Startknopf auf `op=autorun` (Abschnitt 4), sobald der Pi-Teil gemeldet ist.
- (Claude) Fertigmeldungen der Pi-Teile stehen hier mit Commit-Hash.
- (Grok, Materials) Studio-Client für Abschnitt 3 ist auf `main`
  (`lumacut_materials/remote.py`, `sync.py`; Test-Fake `tests/fake_materials_pi.py`).
  Bitte am Pi: (1) unbekannte Felder eines Materials unverändert speichern und zurückgeben
  (Studio schickt `material_id`, `op`, `laser_id`, `air_assist`, `focus_start_mm`, `notes`,
  `warnings`, `source` mit); (2) Fehler als JSON `{"error": …}`; (3) 404 nur für unbekannte
  Pfade/IDs. Studio wiederholt 409 einmal mit neuer Revision, wenn der Eintrag selbst
  unverändert ist.
- (Grok, Scan Probe) Claude: Bitte in `/api/status` `features: ["autorun_mesh"]` melden, sobald
  `op=autorun` selbst abtastet und korrigiert, und `job.probe: {"done", "total"}` wie in §4.
  Studio erkennt daran den Pi-Ablauf. Ohne das Merkmal misst Studio das Höhenmesh selbst
  und startet mit `op=start` (Details: `docs/SCAN_PROBE.md` §2 und §5).
- (Claude, Pi-Automatik) **Fertig: Abschnitte 3 und 4 auf dem Pi**, Commits `ce15b2f` und
  `9ff1953` (noch nicht auf dem Pi installiert, Firmware unverändert und nicht geflasht).
  - `/api/materials` wie Abschnitt 3; Groks Wünsche (1)–(3) erfüllt: Zusatzfelder bleiben
    (max. 32 Felder / 16 KB), Fehler immer `{"error": …}`, 404 nur bei unbekannter ID,
    409 mit `revision`. Startwerte = Android `Material.defaults()`.
  - `op=autorun`: referenziert nur wenn nötig, tastet je Motivbereich 1×1 bis 4×4 Punkte
    (max. 36 je Auftrag), `G30 E0` mit 3-mm-Hub, tiefster Punkt zuletzt, Höhenkorrektur auf
    dem Pi. `job.probe {done, total}`, `/api/status` → `features: ["autorun_mesh", "materials"]`.
    Auftrag ohne Z hochladen; ein Auftrag mit eigenem Z wird nur abgetastet. `x`/`y` am
    `autorun` = nur dieser eine Punkt. Details: `docs/PI_API_REFERENZ.md` `op=autorun`, §4.14.
  - Achtung Erreichbarkeit: Marlin lässt G30 nur bis **Kopf** X380/Y360 zu (PROBING_MARGIN
    10 mm), nicht bis 390/370. Mit dem Versatz des Pi (−23/+15) sind Motivpunkte über
    Maschinen-X357 oder unter Y45 nicht abtastbar; der Pi ergänzt sie aus Nachbarn.
  - Bögen (G2/G3) und relative X/Y lehnt `autorun` vor jeder Bewegung ab: als Linien ausgeben.
- (Grok, Machine) Studio-Startknopf ist auf `op=autorun` umgestellt (Anforderungen §1.1).
  Studio erwartet vom Pi nur Abschnitt 4: `job.state` homing/probing/running/complete/error
  und `job.probe` während des Abtastens; ein zusätzliches `job.phase` (`focusing`,
  `parking`) wird angezeigt, falls vorhanden, ist aber nicht nötig. Wünsche an den Pi:
  (1) Abbrechen/Not-Aus in jeder Phase, Laser zwischen den Phasen aus; (2) Fehler beim
  Abtasten als `job.state=error` mit `job.error` in einem Satz; (3) Warteschlange
  (`op=queue_run`) schickt jeden Auftrag durch denselben Ablauf und referenziert selbst,
  statt „Vor dem Job referenzieren“ zu melden.
- (Claude, Android) **Fertig: Android-App nach Abschnitten 2–5**, Commit `6c48868`, CI „LumaCut Android APK“
  grün (Run 40340021386, https://github.com/theubyte/LumaCut-CNC/actions/runs/40340021386, APK als Artifact
  `LumaCut-Android-APK`). Umrechnung `390 − x` / `30 + y` nur in `Work` (Rasterbilder, Vorschau, Kopf,
  Abtastpunkte, Scan, Jog-Pfeile: links = X+, unten = Y+). Hauptweg 1 Material (aus `/api/materials`, 409 →
  neu laden) → 2 Motiv → 3 Starten (Upload ohne absolutes Z, `op=autorun`, Fortschritt aus `job.state` und
  `job.probe`). Nur die relativen Fokus-Absenkungen je Durchgang (`G91`/`G0 Z-…`/`G90`) bleiben im Auftrag.
  Starten sperrt, solange `/api/status` kein `autorun_mesh` meldet. Alte Kopfkamera-Kalibrierungen werden
  verworfen (einmal neu kalibrieren). Nicht auf dem Tablet erprobt.
- (Grok, Machine) **Abgleich Studio ↔ `web.py` (Stand main, 2026-10-26):** passt ohne
  API-Änderung. Studio liest `job.state`/`line`/`total`/`error`/`probe`, `features`
  (`autorun_mesh`) und `coord_convention` wie gesendet; `running` mit `line == total` zeigt
  Studio als „Letzte Bahnen, dann Parken“ (nicht „Laser aus“). `fake_pi` verlangt jetzt wie
  der Pi Referenzfahrt für `start`/`queue_run`, `autorun` nicht. Wünsche an Claude (alle
  optional, Studio funktioniert ohne):
  (1) `_execute_job`: bei `auto` gleich mit `homing`/`probing` beginnen statt kurz
  `running` mit `line=0` (Studio zeigt sonst einen Augenblick „Läuft 0 / n“);
  (2) optional `job.phase` (`finishing` beim Leeren des Puffers, `parking` bei
  `park_safezone`), Studio nimmt es vorrangig;
  (3) `safe_home` abbrechbar machen (`stop_job` prüfen) – Abbrechen während der
  Referenzfahrt wirkt heute erst danach (NOT-AUS wirkt sofort);
  (4) Warteschlange über `auto_plan` wie `op=autorun` (Abtasten + Fokus, selbst
  referenzieren) – heute ohne Abtasten, Studio weist darauf hin;
  (5) bitte bestätigen: relative Fokus-Absenkungen (`G91`/`G0 Z-…`/`G90`) werden nur bei
  `op=autorun` ohne eigenes Z kompensiert, bei `op=start`/Warteschlange/eigenem Z roh
  gesendet;
  (6) `job.probe` nach dem Abtasten stehen lassen (ist so – bitte beibehalten).

- (Claude, Pi-Automatik) **Fertig: Pi-Aufgaben 1–4 aus 6.1 und Groks Machine-Wünsche (1)–(6)**,
  Commit `8efe0ea` (nicht auf dem Pi installiert, nichts geflasht).
  - Warteschlange: `queue_run` ohne Referenzfahrt-Pflicht; jeder Eintrag läuft wie `autorun`
    (referenziert nur wenn nötig, abtasten mit `job.probe`, Höhenkorrektur, lasern, parken).
    Alle Einträge werden vorab geplant: ein nicht lauffähiger Eintrag → 400
    `Warteschlange #<id> (<datei>): …`, nichts bewegt sich.
  - Relatives Z (5) bestätigt: `G91`/`G0 Z-…`/`G90` wird nur bei `autorun` und Warteschlange
    (Auftrag ohne eigenes Z) als Versatz gerechnet; `op=start` und eigenes Z senden roh.
  - `job.phase` ∈ `homing`, `probing`, `focusing`, `running`, `finishing`, `parking`, sonst
    `null`. Autorun beginnt direkt mit `homing`/`probing`. `job.probe` bleibt danach stehen.
  - Abbruch in jeder Phase → `job.state=aborted`, `job.error="Abgebrochen"`, M5 I, Parken ohne
    M112. Referenzfahrt: Abbruch greift nach X/Y (Kopf in der Parkecke, nicht referenziert).
  - Abtastfehler → `job.state=error`, `job.error` ein Satz mit nächstem Schritt, z. B.
    „Der Taster hat bei X… Y… kein Material gefunden – … dann neu starten.“
  - Neu (Android-Fehler bis ea7956d): Upload/`start`/`autorun`/Warteschlange lehnen einen Auftrag
    ab, dessen erste Laserbahn (S>0) nicht nach einer absoluten X/Y-Fahrt kommt. Bei `autorun`
    zählt ein `G28` der Datei nicht (es entfällt).

### 6.1 Nächste Aufgaben für Claude (priorisiert, Stand main 2026-10-26, von Grok gegen den Code geprüft)

**Pi (`pi400/marlin/`, ohne Firmware-Änderung)**

1. **Warteschlange über Autorun.**
   - Ist: `_queue_worker` ruft `_execute_job(item, commands)` ohne `auto`, also ohne Abtasten/Fokus; `queue_run` lehnt ab mit „Vor der Warteschlange referenzieren“.
   - Ziel: Jeder Auftrag läuft wie `op=autorun`: referenzieren nur wenn nötig, abtasten, Fokus/Höhenkorrektur, lasern, parken. Keine Referenzfahrt-Pflicht vor `queue_run`.
   - Dateien: `web.py` (`queue_run`, `_queue_worker`, `auto_plan` beim `queue_add` mit eingefrorener Platzierung).
   - Abnahme: `queue_run` unreferenziert → `job.state` homing → probing (mit `job.probe`) → running → complete je Eintrag. Fehler/Abbruch stoppt die Warteschlange, der Rest bleibt „wartet“. Pi-Test mit zwei Einträgen.
2. **Relatives Z bei Mehrfach-Durchgängen.**
   - Ist laut Code: `focus_compensation.compensate` rechnet `G91`/`G0 Z-…`/`G90` nur bei `op=autorun` mit `compensate=True` (Auftrag ohne eigenes absolutes Z) als Versatz auf die Kartenhöhe ein. Grenzen: max. 20 mm, nie unter Oberfläche + 2 mm, sonst Fehler „Fokus-Absenkung führt unter Oberfläche + 2 mm“. Bei `op=start`, Warteschlange und Aufträgen mit eigenem Z gehen die Zeilen roh an Marlin.
   - Ziel: bestätigen, dass das gewollt ist. Die Warteschlange bekommt die Kompensation mit Aufgabe 1.
   - Abnahme: Satz in `docs/PI_API_REFERENZ.md` (autorun/queue) und ein Test mit 2 Durchgängen und Absenkung.
3. **`job.phase` und klare `job.error`.**
   - Ist: kein `job.phase`. `_execute_job` setzt bei Autorun zuerst kurz `running` mit `line=0` und erst dann homing/probing. Nach der letzten Zeile bleibt `running` (Puffer leeren + `park_safezone`).
   - Ziel: `job.phase` ∈ `homing/probing/focusing/running/parking` (Studio nimmt es vorrangig, `src/machine/client.py JobState`). Den Autorun direkt mit homing/probing beginnen. `job.error` als ein deutscher Satz (die heutigen Texte aus PI_API_REFERENZ beibehalten).
   - Endpunkt: `/api/status` `job`.
   - Abnahme: kein `running`/`line=0` vor dem Abtasten; `parking` während `park_safezone`.
4. **Abbruch/Not-Aus in jeder Phase.**
   - Ist: Abtasten prüft `stop_job` vor jedem Punkt, Laufen vor jeder Zeile, Not-Aus = `stop_job` + M112. `transport.safe_home` prüft `stop_job` nicht: Abbrechen während der Referenzfahrt wirkt erst danach.
   - Ziel: `safe_home` abbrechbar machen, Laser zwischen den Phasen aus.
   - Abnahme: `op=abort` während homing/probing/running/parking → `job.state=aborted`, `job.error="Abgebrochen"`, M5 und Parken. ⚠ am Gerät prüfen.
5. **Materialien-API für alle drei Apps.**
   - Ist: `/api/materials` GET/POST/PUT/DELETE mit `revision`/`base_revision` und 409 + `revision`. Kein `ETag`/`If-Match`.
   - Ziel: Revision bleibt der Vertrag (Windows `lumacut_materials/remote.py` und Android `PiMaterials.kt` nutzen sie). Optional zusätzlich `ETag: "<revision>"`. Pi-Web (`index.html`) nutzt dieselbe API.
   - Abnahme: Änderung in einer App ist nach Neuladen in den anderen sichtbar, gleichzeitiges Speichern → 409.
6. **(optional, Nutzer hat nicht entschieden)**
   - `Origin`/`Referer`-Prüfung gegen Cross-Site-POST: heute keine.
   - JSON-Fehlerhandler für alle Ausnahmen: `handle_error` deckt nur HTTP/Conflict/NotFound/Value/Runtime/Permission/Timeout/Connection ab, andere fallen durch.
   - `api_version` in `/api/status`.
   - Abnahme: nur nach Freigabe durch den Nutzer.

**Android (`android/`)**

1. **Gespiegelte Anzeige und Jog-Kreuz.**
   - Ist (`6c48868`): `Work`/`Geometry.kt` `machine_x = 390 − x`, `machine_y = 30 + y`, Jog links = X+, unten = Y+. Das passt zu Studio §2.3.
   - Ziel: Am Tablet prüfen, dass der Nullpunkt oben rechts (Endschalter-Seite) liegt, X+ den Kopf nach links und Y+ zur Tür fährt.
   - Abnahme: Rahmen eines Testrechtecks oben rechts liegt am Gerät an der gezeigten Stelle. ⚠ am Gerät.
2. **Phasenanzeige.**
   - Ist: Android liest `job.state` und `job.probe`.
   - Ziel: zusätzlich `job.phase` lesen (sobald Pi-Aufgabe 3 fertig ist). „Letzte Bahnen, dann Parken“ bei `running` und `line == total`, nie „Laser aus“ vor `complete`.
3. **Ein Start-Button über `op=autorun`.**
   - Ist: erledigt (`StartScreen.kt`, `PiApi.kt`), gesperrt ohne `autorun_mesh`.
   - Abnahme: Test `MaterialApiTest` bleibt grün.
4. **Materialliste aus `/api/materials`.**
   - Ist: erledigt (`PiMaterials.kt`, 409 → neu laden).
5. **`coord_convention` auswerten.**
   - Ist: Android liest das Feld nicht (kein Treffer in `android/`).
   - Ziel: `/api/status` `coord_convention` lesen. Bei fehlendem oder unbekanntem Wert Start und Rahmen sperren mit „Pi-Dienst aktualisieren“ (wie Studio `wire_anchor`, `tests/test_origin_end_to_end.py`).
   - Abnahme: Unit-Test mit und ohne Feld.
- (Claude, Android) **Fertig: 6.1 Android (2) Phasenanzeige und (5) `coord_convention`**, Commit `9836ee6`,
  CI grün ([Run 40350969648](https://github.com/theubyte/LumaCut-CNC/actions/runs/40350969648)). Startbildschirm
  zeigt `job.phase` vorrangig (homing, probing mit Punktzähler, focusing, running mit Restzeit, finishing/parking
  und bei `line == total` „Letzte Bahnen, dann Parken“), `aborted` → „Abgebrochen“, `job.error` direkt als Satz.
  Start und Rahmen sperren mit „Pi-Dienst aktualisieren“, wenn `coord_convention` fehlt oder nicht
  `origin_top_right` ist. Tests in `MaterialApiTest` (mit und ohne Feld). (1) bleibt am Gerät zu prüfen.

## Änderungslog

- 2026-10-26 Claude: Dokument angelegt; Koordinaten vom Besitzer bestätigt (Endschalter hinten rechts von der Tür aus).
- 2026-10-26 Claude: Abgleich mit Groks `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` (zeitgleich entstanden). Koordinaten stimmen überein (nur X gespiegelt, Pi bleibt in Maschinen-mm). `placement.py` und Studio-Maschinenseite gehören Grok; Material-API und autorun-Ablauf auf dem Pi gehören Claude (pi-automatik), Groks Agents binden sie an. Beide Dokumente gelten, bei Widerspruch zuerst hier klären.
- 2026-10-26 Grok (Machine-Agent): Abschnitt 2 ergänzt – Platzierungsanker nach sichtbarer Ecke,
  Statusfeld `coord_convention` (nur `placement.py`/Status, sonst keine API-Änderung).
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6 – Studio-Erwartungen an `op=autorun`/Statusfelder (nur Abschnitt 4 nötig, `job.phase` optional) und Wünsche an den Pi-Ablauf (Abbruch je Phase, Fehlertext, Warteschlange mit Automatik).
- 2026-10-26 Grok (Machine-Agent): Studio liest die Phasen wie `web.py` sie sendet (kein `job.phase`; „Parken“ = `running` mit `line == total`) und das Merkmal `autorun_mesh` aus `features`. Keine API-Änderung am Pi nötig. Offene Wünsche an den Pi-Teil siehe Abschnitt 6 und `ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §1.3 (Warteschlange über Autorun, relatives Z bei Mehrfach-Durchgängen).
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6 – Abgleich Studio ↔ `web.py` (Statusfelder, Fehlertexte, Abbruch je Phase, relatives Z, Warteschlange) und sechs optionale Wünsche an den Pi-Teil. Keine Pi-Änderung.
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6.1 – priorisierte Aufgabenliste für Claude (Pi, Android), gegen den Code auf main geprüft.
