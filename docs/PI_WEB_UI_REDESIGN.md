# Pi-Weboberfläche (Stand 28.10.2026)

Datei: `pi400/marlin/index.html`. Eine einzige, eigenständige HTML-Datei: kein CDN, keine Webfonts,
kein Build, Vanilla-JS, deutsche Texte. `web.py` liefert sie unverändert unter `/` aus.
Seit dem 28.10.2026 pflegt Claude die Oberfläche (vorher Grok).

## 1. Ziele

- Gleiches Aussehen wie die Android-App: dieselben Farben (`android/app/.../ui/Theme.kt`), hell und
  dunkel, ruhige Karten, große Touch-Ziele.
- Seiten statt einer langen Seite: links eine Navigationsleiste (auf dem Handy unten).
- Alles, was der Pi speichert, ist hier einstellbar. Was nur dieses Gerät betrifft
  (Farbschema, Tastatur-Joggen, Töne), liegt im `localStorage` des Browsers.
- Die Sicherheitslogik ist dieselbe wie vorher (Abschnitt 6).

## 2. Aufbau

```
<nav class="rail">            Steuerung · Aufträge · Material · Kamera · Einstellen · System
<header id="statusPanel">     Gerätename, Zustand, Chips, Kopfposition, NOT-AUS (#stop)
  #jobStrip                   Fortschritt, Restzeit, Phasen (#phaseSteps), Abbrechen
  #estopBanner, #staleBanner
<main id="app">
  section.page[data-page=steuerung]     Arbeitsfläche (SVG #bed), Position, Joggen, Licht & Abluft
  section.page[data-page=auftraege]     Hochladen (Ziehen & Ablegen), Liste mit Vorschaubildern,
                                        Statistik, Material (für alle Geräte), Platzierung, Start, Warteschlange
  section.page[data-page=material]      Materialtabelle: suchen, filtern, bearbeiten, kopieren,
                                        löschen, „Verwenden“, Export/Import als JSON
  section.page[data-page=kamera]        Bild/Live, Fadenkreuz, Vollbild, Bildeinstellungen,
                                        Scan der Arbeitsfläche, Kalibrier-Übersicht
  section.page[data-page=einstellungen] Fokus & Taster, Gerät, Bewegung, Abluft, Ursprung,
                                        Linienlaser, Maschinenfreigabe, Diese Oberfläche
  section.page[data-page=system]        Zustand, Marlin-Abfragen (op=report), Protokoll,
                                        SKR-Firmware, Android-App, LightBurn, Sicherung
<dialog>                      #askDlg (Rückfragen), #matDialog, #palette (Strg+K), #keysDlg (?)
```

Navigation über den Hash (`#steuerung` …); alte Links wie `#calibrationPanel` führen auf die
passende Seite.

## 3. Bedienung, die neu ist

- **Arbeitsfläche:** Mausrad/Knöpfe zoomen, ziehen verschiebt, Doppelklick zeigt alles. Antippen
  öffnet ein Menü an dieser Stelle: *Hierhin fahren* (`op=moveto`, Laser aus), *Hier abtasten*
  (`op=probe` mit x/y), *Als Ursprung setzen* (`op=origin_set`). Nur wenn referenziert, frei und
  freigegeben; Abtasten/Ursprung nur im Schneidbereich. Ebenen: Scanbild der App
  (`/api/workspace/scan`), Laserwege, Leerfahrten, Raster.
- **Aufträge:** Vorschaubilder und Statistik (Dauer, Laserweg, Motivgröße, Leistung, Vorschub)
  rechnet der Browser aus dem G-Code (`analyseGcode`, Dateien bis 8 MB, Vorschaubilder bis 3 MB).
  Platzierung: „Wie im G-Code“, „An der Kopfposition“ oder „Am Ursprung“ mit Bezugspunkt
  (`origin`/`anchor` an `start`, `autorun`, `queue_add`; „Platzierung prüfen“ = `op=place`).
- **Material:** Die Auswahl schreibt `PUT /api/workspace {material}` – sie gilt sofort auf allen
  Geräten, und ohne Material startet kein Auftrag (der Pi verlangt es).
- **Kopfzeile:** Restzeit aus dem Fortschritt; Ton und Browser-Benachrichtigung bei Auftragsende
  (einstellbar unter „Diese Oberfläche“).
- **Tastatur:** Strg+K Befehlsliste, `?` Kürzel, `g` + Buchstabe wechselt die Seite, Esc Esc löst
  den NOT-AUS-Dialog aus, Pfeiltasten/Bild↑↓ joggen (nur auf „Steuerung“, abschaltbar).

## 4. Pi-Seite (web.py), dafür ergänzt

- `POST /api/settings`: jedes Feld optional; neu `machine_name`, `exhaust_auto`, `exhaust_after_s`.
- Abluft-Automatik: `M8` beim Auftragsstart, `M9` nach dem Nachlauf (nicht, wenn inzwischen ein
  Auftrag läuft oder jemand anderes die Steuerung hat).
- `op=report` mit `cmd` ∈ `M105 M114 M115 M119 M503` (nur lesen).
- `GET /api/backup`: alle Einstellungen, Materialien, Arbeitsstand, Kamera-Kalibrierung als JSON.
- `features` meldet `report`, `backup`, `exhaust_auto`; ältere Pis werden erkannt (die Oberfläche
  blendet dann Sicherung aus und fällt bei Abfragen auf `op=info/position/endstops` zurück).

Details: [`PI_API_REFERENZ.md`](PI_API_REFERENZ.md).

## 5. Feste Strings für Tests

`tests/test_pi_web_ui.py` und `tests/test_marlin_gateway.py` prüfen u. a.: Spiegelung des Betts nur
in `#bedFlip` (`translate(W,0) scale(-1,1)`, keine Texte darin), Jog-Kreuz-Reihenfolge und
Pfeiltasten-Zuordnung, Material-API, `"/api/settings"`, `id="zOffset"`, `id="saveZSettings"`,
`estimated_tip_gap_mm`, `const raw=await r.text();`, „Keine Anmeldung erforderlich“,
„MARLIN CONTROL OS“, `M3 I`, `M112`, `M114`, `M115`, `M119`.

## 6. Sicherheitslogik (nicht aufweichen)

- `#stop` (M112) ist **nie** `disabled`, auch nicht bei API-Fehler; vor dem Auslösen fragt ein
  Dialog nach.
- `motionFree(s)` = API erreichbar ∧ Steuerung frei ∧ ¬`busy` ∧ `activity==="idle"` ∧ ¬`emergency_latched`.
  Alle `[data-motion]`-Knöpfe sind gesperrt, wenn nicht frei, ohne `config.validated`, oder
  (bei `data-needs-home`/`start`) wenn nicht referenziert. Dasselbe gilt im Menü der Arbeitsfläche.
- Joggen nur ±0,1/1/10 mm, nur referenziert und frei; `jogInFlight` verhindert Aufstauen;
  gedrückt gehaltene Tasten erzeugen keine Schrittkette.
- Ist Z unbekannt (`home_needs_confirm`), fragt Referenzieren/Auftrag erst „Kopf frei?“ und sendet
  dann `clear=1`.
- API-Fehler ⇒ `lockAll()` sperrt Bewegung, Jog und Zubehör.
- Flashen, Löschen und Warteschlange leeren nur nach Rückfrage.

## 7. Testen

```bash
python -m pytest tests -q
```

Ohne Maschine (Mock-Server setzt den Maschinenzustand künstlich – **nie auf dem Pi starten**):

```bash
LUMACUT_DATA=$(mktemp -d) PYTHONPATH=pi400 python tests/ui_mock_server.py idle 8099
```

Szenarien: `idle`, `running` (hält `machine.lock` → Veraltet-Banner), `autorun` (Phasen), `oldpi`,
`offline`. Dann `http://127.0.0.1:8099/` in Desktop-, Tablet- und Handygröße öffnen.
Auf dem Pi: `http://<Pi-Adresse>:8080/`, NOT-AUS-Rückfrage, Jog-Sperre ohne Referenzfahrt und
Rahmen mit **getrennter** Laserversorgung prüfen.
