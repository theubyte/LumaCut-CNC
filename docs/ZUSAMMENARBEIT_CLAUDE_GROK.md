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

- (Grok, Scan Probe) **Wunsch Besitzer 2026-10-26 – nicht erreichbare Abtastpunkte nicht mehr abbrechen**
  (Anforderungen §1 und §2.4):
  - **Stand `b966c89` (Claude):** Teil erledigt – Kopf beim Abtasten X10–380 / Y10–360, Ersatzpunkt
    höchstens 40 mm daneben (`HeightGrid.probe_at`), 400 nur noch, wenn auch so nichts erreichbar ist;
    Android `Scan.reachable` gleich. Studio-Vorprüfung ist angeglichen (Grok, `reach.py`). **Offen:**
    Warnungsliste (`job.warnings`) vom Pi und Anzeige in Android.
  - Pi: Der 400 „Kein Abtastpunkt erreichbar …“ (`heightmap._mark_reachable`, `pi400/marlin/heightmap.py:271`)
    darf `autorun`/Mesh nicht mehr abbrechen. Nicht erreichbare Punkte auf die nächste erreichbare
    Tasterposition klemmen (Laserpunkt in `[30+dx, 380+dx] × [30+dy, 360+dy]` ∩ Arbeitsbereich),
    dort messen, Wert für den Originalpunkt verwenden, Auftrag weiterlaufen lassen.
  - Antwort von `autorun` und `/api/status` → `job.probe.warnings`: Liste
    `{"x", "y", "probed_x", "probed_y", "side": "links|rechts|oben|unten", "distance_mm"}` (Bildschirmseite) plus ein
    deutscher Satz, z. B. „Achtung: 3 Abtastpunkte am linken Rand (Maschine X > 357) nicht erreichbar –
    stattdessen bis 12 mm daneben gemessen. Ist das Werkstück dort kleiner, landet der Taster neben dem
    Werkstück auf dem Bett. Gelasert wird trotzdem.“
  - Fehler bleiben nur: Taster löst nicht aus / kein Material, Not-Aus, Abbruch.
  - Optional: `probe_reach_mm` in `/api/status`, damit Apps den Bereich anzeigen.
  - Android: Warnung anzeigen (gleicher Wortlaut), kein Abbruch; nutzt nur den Pi-Vertrag.
  - Studio macht dasselbe auf seiner Seite (Vorprüfung = Warnung, eigenes Mesh mit Ersatzpunkten).

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

7. **Taster-Reichweite: nicht mehr ablehnen, sondern nah daneben tasten und warnen** (Grok, Machine; Meldung und Vorgabe des Besitzers 2026-10-26).
   - **Stand `b966c89`:** Ablehnung und Klemmen erledigt (Ersatzpunkt ≤ 40 mm, Kopf-Min 10 statt 30 – oberer Rand jetzt direkt abtastbar, die Fälle unten laufen alle). **Offen bleibt nur `job.warnings`** (Abschnitt „Warnung im Status“ unten) und ⚠ G30 bei Kopf X/Y 10 am Gerät prüfen. Der folgende Ist-Stand ist der vor `b966c89`.
   - Ist: Die Meldung entsteht nur in `pi400/marlin/heightmap.py` `_mark_reachable` (Z. ~276): sie markiert je Rasterpunkt `probe_reachable(x, y)`, verwirft Regionen ohne erreichbaren Punkt und wirft `ValueError("Kein Abtastpunkt erreichbar: …")`, wenn keine Region bleibt → `web.py auto_plan` → HTTP 400, der Auftrag startet nicht.
   - Ist geprüft (`software/lumacut-studio-native/tests/test_machine_probe_reach.py`, folgt im nächsten Grok-Commit, ruft das echte `heightmap.plan_probe` und `MarlinTransport.probe_reachable` auf):
     - Grenze stimmt mit dem Code überein: Kopf beim G30 X30–380 / Y30–360 (`transport.py` `_probe_head_ok`, `PROBE_HEAD_MAX`), Versatz Spitze minus Laser X−23 / Y+15 → abtastbare Laserpunkte **X30–357 / Y45–370** (inklusiv, ohne Rundung). (30, 45) geht, (30, 44.99) nicht, (357.01, …) nicht. Vorzeichen passt zu Scan Probe `geometry.py` und Firmware-Offset 0.
     - Zu streng: `_per_side` nimmt bei Regionslänge < 20 mm nur die Mitte, `_grid` sonst Punkte 5 mm innen. Geprüft wird nur dieser Rasterpunkt, nicht die erreichbare Teilfläche. Beispiele (Maschinen-mm, Rechteck x0–x1 × y0–y1):
       - 100–120 × 30–47 → Region Y30–49, ein Punkt Y39,5 → abgelehnt, obwohl Y45–49 erreichbar ist.
       - 200–210 × 38–48 → Punkt (205, 43) → abgelehnt; dieselbe Form bei Y42–52 → Punkt (205, 47) → läuft.
       - 352–366 × 200–210 → Punkt X359 → abgelehnt, obwohl X350–357 erreichbar ist.
       - Richtig abgelehnt: 30–50 × 30–40 (Nullpunkt-Ecke), 100–140 × 30–42, 360–390 × 200–230, 360–390 × 340–370.
     - Kopf-Minimum ist die Schutzzone 30, Marlin lehnt laut Kommentar erst unter `PROBING_MARGIN` 10 ab. Bei Kopf Y15–30 läge die Spitze bei Y30–45 (Schneidbereich).
     - Meldung ohne Motiv-Box und ohne erreichbaren Bereich („Motiv weiter in die Mitte schieben“). Studio hängt den Bereich bis dahin selbst an (`client.explain_probe_error`, nächster Grok-Commit), das ist nur eine Rechnung aus dem Status.
   - **Soll (Vorgabe des Besitzers 2026-10-26): nie abbrechen, nah daneben tasten und warnen.**
     - Keine Ablehnung mehr wegen Reichweite: `_mark_reachable` wirft kein „Kein Abtastpunkt erreichbar“ mehr, `web.py auto_plan` (Z. ~851, auch Warteschlange Z. ~1171/1207) plant weiter.
     - Jeder nicht erreichbare Rasterpunkt wird auf den **nächsten erreichbaren Punkt** geklemmt (Klemmen auf X30–357 / Y45–370 bzw. allgemein `safe_zone`..`PROBE_HEAD_MAX` + Versatz), z. B. (110, 39,5) → (110, 45), (359, 205) → (357, 205), (40, 35) → (40, 45). Auch Regionen ohne jede erreichbare Fläche werden so getastet, statt verworfen zu werden.
     - Die Kopf-Grenzen beim G30 (`_probe_head_ok`, Schutzzone, `PROBE_HEAD_MAX`, Marlin `PROBING_MARGIN`) bleiben unverändert: geklemmt wird der Messpunkt, nicht die Grenze. Laser bleibt beim Tasten aus.
     - Der Auftrag läuft weiter und lasert. Die Höhenkarte nutzt den geklemmten Messwert für den ursprünglichen Rasterpunkt.
     - Warnung im Status, z. B. `job.warnings: [{"code": "probe_clamped", "text": "…", "box": [xmin, ymin, xmax, ymax], "points": [{"want": [x, y], "probed": [x, y], "distance_mm": d}]}]`. Text als ein deutscher Satz mit Box, Punkten und Abstand, z. B. „Taster nicht erreichbar bei X110 Y39.5 – stattdessen bei X110 Y45 getastet (5.5 mm daneben), Motiv X100–120 / Y30–47. Ist das Werkstück kleiner, misst der Taster neben dem Werkstück auf dem Bett – Fokus prüfen.“ Bleibt nach dem Auftrag stehen wie `job.probe`, wird beim nächsten Start geleert.
     - Optional, nur nach Prüfung am Gerät: Kopf beim G30 bis X/Y 15 (statt 30) zulassen. ⚠ am Gerät.
     - Optional: Feature-Name `probe_clamp` (und `queue_autorun`) in `FEATURES`, damit Studio/Android erkennen, dass der Pi klemmt statt ablehnt.
   - Abnahme (Pi-Test): kleines Werkstück an der Ecke, Rechteck 30–50 × 30–40 → `autorun` läuft (homing → probing → running → complete), Messpunkt (40, 45), `job.warnings` enthält Box 30/30/50/40, want (40, 35), probed (40, 45), Abstand 10 mm. Ebenso 100–120 × 30–47 und 352–366 × 200–210. Warteschlange mit einem solchen Eintrag läuft durch. Kopf-Position bei jedem G30 bleibt in X30–380 / Y30–360.

8. **Android: Warnung zur geklemmten Abtastung** (gehört zu Pi 7; Android-Teil siehe unten Android 6).

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
6. **Warnung „Taster nah am Werkstück“ statt Abbruch** (Vorgabe des Besitzers, zu Pi 7).
   - Ist: Android zeigt den 400-Fehler „Kein Abtastpunkt erreichbar …“ von `op=autorun`; der Auftrag startet nicht.
   - Ziel: `job.warnings` (Pi 7) lesen und deutlich anzeigen (gelb, mit Box, Punkt und Abstand), solange der Auftrag läuft und danach. Start nicht blockieren. Wenn der Pi vorab eine Warnung liefert (z. B. aus `op=place`/Plan), optional Rückfrage „Taster misst nah am Werkstück-Rand, evtl. auf dem Bett – trotzdem lasern?“.
   - Abnahme: Unit-Test mit Status mit `job.warnings` → Text sichtbar, Start-Knopf bleibt aktiv; ohne Feld keine Änderung.
- (Claude, Android) **Fertig: 6.1 Android (2) Phasenanzeige und (5) `coord_convention`**, Commit `9836ee6`,
  CI grün ([Run 40350969648](https://github.com/theubyte/LumaCut-CNC/actions/runs/40350969648)). Startbildschirm
  zeigt `job.phase` vorrangig (homing, probing mit Punktzähler, focusing, running mit Restzeit, finishing/parking
  und bei `line == total` „Letzte Bahnen, dann Parken“), `aborted` → „Abgebrochen“, `job.error` direkt als Satz.
  Start und Rahmen sperren mit „Pi-Dienst aktualisieren“, wenn `coord_convention` fehlt oder nicht
  `origin_top_right` ist. Tests in `MaterialApiTest` (mit und ohne Feld). (1) bleibt am Gerät zu prüfen.
- (Claude, Android) **Fertig: Auftrag „Laser attraktiver“ (Importe, Kontur, Extras)**, Commit `5329cbd`, CI grün
  ([Run 40375500748](https://github.com/theubyte/LumaCut-CNC/actions/runs/40375500748), APK als Artifact
  `LumaCut-Android-APK`). Importieren (xcs, lbrn, HPGL, PDF/AI, Bildformate, Erkennung am Inhalt), Kontur/Sticker
  mit Vorschau, Bild anpassen (Jarvis/Stucki, Helligkeit/Kontrast/Schärfe/Invertieren), QR-Code, Text im Bogen,
  Raster-Kopien, Formen, Umriss für Vektoren. Alles in `core` mit Tests. Offen/ehrlich: `.xcs` und QR nicht gegen
  echte Dateien/Scanner geprüft; Boxgenerator nicht gebaut. Nicht am Gerät erprobt.

## Änderungslog

- 2026-10-26 Claude: Dokument angelegt; Koordinaten vom Besitzer bestätigt (Endschalter hinten rechts von der Tür aus).
- 2026-10-26 Claude: Abgleich mit Groks `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` (zeitgleich entstanden). Koordinaten stimmen überein (nur X gespiegelt, Pi bleibt in Maschinen-mm). `placement.py` und Studio-Maschinenseite gehören Grok; Material-API und autorun-Ablauf auf dem Pi gehören Claude (pi-automatik), Groks Agents binden sie an. Beide Dokumente gelten, bei Widerspruch zuerst hier klären.
- 2026-10-26 Grok (Machine-Agent): Abschnitt 2 ergänzt – Platzierungsanker nach sichtbarer Ecke,
  Statusfeld `coord_convention` (nur `placement.py`/Status, sonst keine API-Änderung).
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6 – Studio-Erwartungen an `op=autorun`/Statusfelder (nur Abschnitt 4 nötig, `job.phase` optional) und Wünsche an den Pi-Ablauf (Abbruch je Phase, Fehlertext, Warteschlange mit Automatik).
- 2026-10-26 Grok (Machine-Agent): Studio liest die Phasen wie `web.py` sie sendet (kein `job.phase`; „Parken“ = `running` mit `line == total`) und das Merkmal `autorun_mesh` aus `features`. Keine API-Änderung am Pi nötig. Offene Wünsche an den Pi-Teil siehe Abschnitt 6 und `ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §1.3 (Warteschlange über Autorun, relatives Z bei Mehrfach-Durchgängen).
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6 – Abgleich Studio ↔ `web.py` (Statusfelder, Fehlertexte, Abbruch je Phase, relatives Z, Warteschlange) und sechs optionale Wünsche an den Pi-Teil. Keine Pi-Änderung.
- 2026-10-26 Grok (Machine-Agent): Abschnitt 6.1 – priorisierte Aufgabenliste für Claude (Pi, Android), gegen den Code auf main geprüft.
