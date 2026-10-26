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

## Änderungslog

- 2026-10-26 Claude: Dokument angelegt; Koordinaten vom Besitzer bestätigt (Endschalter hinten rechts von der Tür aus).
- 2026-10-26 Claude: Abgleich mit Groks `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` (zeitgleich entstanden). Koordinaten stimmen überein (nur X gespiegelt, Pi bleibt in Maschinen-mm). `placement.py` und Studio-Maschinenseite gehören Grok; Material-API und autorun-Ablauf auf dem Pi gehören Claude (pi-automatik), Groks Agents binden sie an. Beide Dokumente gelten, bei Widerspruch zuerst hier klären.
- 2026-10-26 Grok (Machine-Agent): Abschnitt 2 ergänzt – Platzierungsanker nach sichtbarer Ecke,
  Statusfeld `coord_convention` (nur `placement.py`/Status, sonst keine API-Änderung).
