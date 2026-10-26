# Pi-Weboberfläche – Redesign (Oktober 2026)

Datei: `pi400/marlin/index.html` (eine einzige, eigenständige HTML-Datei: kein CDN, keine Webfonts,
Vanilla-JS, deutsche UI-Texte). Ausgeliefert unverändert von `pi400/marlin/web.py` unter `/`.
**`web.py` wurde nicht geändert**, alle API-Verträge sind identisch (siehe
[`PI_API_REFERENZ.md`](PI_API_REFERENZ.md), gepflegt vom Machine Agent).

Dieses Dokument ist die Übergabe für Claude, Grok und andere Agents: was geändert wurde, warum,
und wie man sicher weiterarbeitet.

## 1. Ziele

- Modernes, ruhiges Bedienpult – klarer als LightBurn-/xTool-Web-UIs.
- Status oben (verbunden, referenziert, SKR-Zustand, Steuerung, Laser, Job-Fortschritt), Steuerung links, Aufträge rechts.
- Große Touch-Ziele (min. 48 px, Jog-Tasten 64 px), gute Lesbarkeit, dunkles Theme wie LumaCut Studio.
- Responsiv für Desktop (≥1240 px, 3 Spalten), Tablet (700–1240 px, Bett oben + 2 Spalten), Smartphone (1 Spalte).
- Alle bisherigen Funktionen bleiben erhalten; Sicherheitslogik ist strenger statt lockerer.

## 2. Änderungsprotokoll

| Bereich | Vorher | Jetzt |
|---|---|---|
| Kopfzeile | Titel + lose Statuszeilen | Sticky `#statusPanel`: Marke, 5 Status-Chips (Farbe ok/warn/danger), großer roter **NOT-AUS** (`#stop`), Job-Leiste mit Fortschrittsbalken, Prozent und „Abbrechen“ |
| Not-Aus | Button in der Seite | Immer sichtbar oben rechts, **nie deaktiviert**, `confirm()` bleibt; bei verriegeltem Not-Aus rotes Banner `#estopBanner` mit `#estopReset` |
| Veraltete Daten | – | Gelbes Banner `#staleBanner`, wenn `busy` und `stale_ms` > 2,5 s (oder fehlt); Badge `#staleBadge` |
| Bewegung (links) | Buttons untereinander | Karte `#controlPanel`: Home (primär), G30-Abtasten, Parken; Schrittweite als Segment-Schalter (0,1/1/10 mm, Hidden-Input `#step` bleibt); Jog-Kreuz X/Y + separate Z-Wippe; Zubehör LED/Abluft als Toggle-Kacheln mit EIN/AUS-Zustand; LightBurn-Homing-Hinweise im `<details>` |
| Mitte | Positionstext | DRO `#position` mit `#posX/#posY/#posZ` (Mono, groß), Firmware-Kennung `#board`, SVG-Bettansicht `#bed` (Arbeitsraum aus `config.travels`, 30-mm-L-Safezone schraffiert aus `safe_zone_xy_mm`, Motiv-Bounds + Messpunkt-Kandidaten nach „Motiv analysieren“, Laserkopf-Fadenkreuz live) |
| Aufträge (rechts) | Upload + Auswahl + Start | Karte `#jobsPanel`: Upload, Auswahl, **Löschen** (`#deleteJob`, mit Bestätigung), Motiv analysieren, **Rahmen fahren** (neu, `op=frame mode=box`), Auftrag starten, Ein-Klick-Autorun, Geometrie-Ausgabe, **Warteschlange** (neu: einreihen, starten, anhalten/fortsetzen, überspringen, entfernen, leeren) |
| Einrichtung | lange Seite | Tab-Karte (ARIA `role=tab`, Pfeiltasten, letzter Tab in `localStorage['lumacut.tab']`, `#hash` wird unterstützt): **Fokus & Taster**, **Diagnose & Protokoll**, **Maschinenfreigabe**, **SKR-Firmware**, **LightBurn** |
| Meldungen | Textzeile | Toast `#alert` unten rechts; Erfolg verschwindet nach 7 s, Fehler bleiben bis Klick |
| Buttons | sofort | Laufende Anfragen zeigen Spinner und sperren den Button (`withPending`), kein Doppel-Klick |
| Tastatur | – | Optionales Joggen: ←/→ X, ↑/↓ Y, Bild↑/Bild↓ Z, 1/2/3 Schrittweite. Ignoriert in Eingabefeldern und bei Auto-Repeat |

## 3. Struktur

```
<header id="statusPanel">        Marke · Chips · NOT-AUS · Job-Leiste · Banner (Not-Aus / veraltet)
<main id="app">
  <div class="layout">           grid-template-areas: "motion center job"
    <section id="controlPanel">  Bewegung, Jog, Zubehör
    <section id="centerPanel">   DRO, Bettansicht
    <section id="jobsPanel">     Upload, Auftrag, Rahmen, Start, Warteschlange
  </div>
  <section class="card tabs">    Tabs: calibration | diagnose | commission | firmware | lightburn
</main>
<div id="alert">                 Toast
<script>                         ein Block, keine Abhängigkeiten
```

CSS: Design-Tokens als CSS-Variablen in `:root`, danach Basis, Komponenten (Karte, Chip, Button,
Segment, Jog, Toggle, DRO, Bett, Queue, Tabs), zuletzt Media-Queries (1240 / 900 / 700 / 420 px,
`prefers-reduced-motion`).

JS (Reihenfolge im Skript): Helfer (`$`, `fmt`, `show`) → `api()` (unverändert übernommen, inkl.
Fehlertext-Auswertung) → `withPending`/`call(op, fields, button)` → `refresh()` (pollt
`/api/status` alle 1,8 s) → `applyStatus(s)` (Chips, Banner, Sperren, Jobleiste, Zubehör, Queue,
Bett) → `files()` (pollt `/api/jobs` alle 12 s) → Aktionen, Jog, Tastatur, Einstellungen,
Inbetriebnahme, Firmware, Tabs.

## 4. Element-IDs

**Alle IDs der alten Oberfläche sind erhalten** (geprüft per Diff der `id=`-Listen), u. a.:
`stop, estopReset, connectState, homed, state, owner, jobStatus, jobProgress, jobDetails, abortJob,
refreshButton, step, position, board, uploadForm, file, jobSelect, previewGeometry, geometryOutput,
zSettings, zOffset, zClearance, focusGap, probeX, probeY, saveZSettings, tipGap, focusAdjust,
workpieceSafety, safety, commands, errors, clearLog, console, commissionCheck, commissionEnable,
commissionDisable, firmwareForm, firmwareFile, firmwareFlash, firmwareStatus, firmwareProgress,
hostname`. Ebenso bleiben `data-action="home|probe|start|autorun|connect|info|position|endstops"`
und `data-axis`/`data-direction` am Jog.

**Neu:** `statusPanel, chipConnect, chipHomed, chipState, chipOwner, chipLaser, laserState,
activityLabel, jobBar, jobPercent, estopBanner, staleBanner, staleBadge, app, controlPanel,
centerPanel, jobsPanel, posX, posY, posZ, activity, jogInfo, jogHint, bed*, deleteJob, frameJob,
fileCount, queueState, queueAdd, queuePause, queueList, queueClear, tab-*, calibrationPanel,
diagnosePanel, commissionPanel, firmwarePanel, lightburnPanel, lbClients, statusAge`.
Attribute: `data-step` (Segment), `data-accessory="light|exhaust"`, `data-queue-op`,
`data-motion`, `data-needs-home`.

Die Tests in `tests/test_marlin_gateway.py` prüfen Strings in `index.html` (u. a. „MARLIN CONTROL OS“,
`M3 I`, `M112`, `M114`, `M115`, `M119`, `"/api/settings"`, `estimated_tip_gap_mm`, `id="zOffset"`,
`id="saveZSettings"`, „Keine Anmeldung erforderlich“, kein `X-LumaCut-Key`). **Diese Strings nicht entfernen.**

## 5. Genutzte API (unverändert)

| Endpoint | Verwendung |
|---|---|
| `GET /api/status` | Polling 1,8 s: `connected, identity, state, homed, owner, busy, stale_ms, activity, job, frame, queue, config.validated, config.travels, position, lights, exhaust, laser_armed, emergency_latched, safe_zone_xy_mm, probe_minimum_z, laser_focus_z, cooldown_remaining_s, command_count, serial_errors, lightburn_clients, recent, firmware_update, firmware_upload_supported` |
| `POST /api/action` | `op=` `estop`, `estop_reset`, `connect`, `home`, `info`, `position`, `endstops`, `probe`, `park`, `jog` (`axis`, `distance` ∈ ±0.1/1/10), `light`/`exhaust` (`on`=1/0), `start`/`autorun` (`name`), `abort`, `frame` (`gcode`, `mode=box`), `queue_add` (`name`, `origin=absolute`), `queue_run`, `queue_pause`, `queue_skip`/`queue_remove` (`id`), `queue_clear` |
| `GET/POST /api/settings` | Fokus- & Taster-Werte |
| `POST /api/commission` | Freigabe prüfen/aktivieren/zurückziehen (`confirm=TESTS_BESTANDEN_LASER_GETRENNT`) |
| `POST /api/firmware` | firmware.bin hochladen + flashen (mit `confirm()`) |
| `GET /api/jobs`, `POST /api/upload`, `POST /api/jobs/<f>/delete`, `GET /api/jobs/<f>/geometry` | Auftragsliste, Upload, Löschen, Motivanalyse |

**Rahmen fahren:** Der Client baut aus den Bounds von `/geometry` ein Rechteck-Programm
(`G21`, `G90`, `M5 I`, `G0 … F3000`, 5 Eckpunkte, `M5 I`) und sendet es als `op=frame mode=box`. Der Server
prüft es mit `frame_program()` (nur G0/G1 X/Y, innerhalb `travels`, F 60–9000) – mit dem
Mock-Server verifiziert („Rahmenfahrt gestartet (Rechteck, Laser aus)“).

## 6. Design-Tokens (aus `software/lumacut-studio-native/src/lumacut_canvas/theme.py`)

| Token | Wert | | Token | Wert |
|---|---|---|---|---|
| `--bg` | `#0b0e13` | | `--text` | `#edf2f7` |
| `--panel` | `#10141b` | | `--text-dim` | `#93a1b5` |
| `--surface` | `#131820` | | `--accent` | `#4cd4b0` |
| `--surface-2` | `#1a212b` | | `--accent-text` | `#09251f` |
| `--border` | `#28303d` | | `--accent-bg` | `#173a33` |
| `--border-hover` | `#526275` | | `--danger` | `#f36b73` |
| `--warn` | `#f2c46d` | | `--touch` | `48px` |

Schrift: System-Stack (`system-ui, Segoe UI, Roboto…`), Zahlen/Logs in `ui-monospace`. Keine Webfonts.

## 7. Sicherheitslogik (bitte nicht aufweichen)

- `#stop` (M112) ist **nie** `disabled`, auch nicht bei API-Fehler; `confirm()` bleibt.
- `motionFree(s)` = API erreichbar ∧ Steuerung frei ∧ ¬`busy` ∧ `activity==="idle"` ∧ ¬`emergency_latched`.
  Alle `[data-motion]`-Buttons sind gesperrt, wenn nicht frei, wenn `config.validated` fehlt, oder
  (bei `data-needs-home`/`start`) wenn nicht referenziert.
- Jog nur ±0,1/1/10 mm (Whitelist `STEPS`), nur wenn referenziert und frei; `jogInFlight` verhindert
  das Aufstauen von Jog-Befehlen.
- Während Job, Rahmenfahrt oder laufender Warteschlange ist jede Bewegung gesperrt.
- `busy` + `stale_ms` > 2500 ms ⇒ Daten als veraltet markiert (Banner), Bewegung bleibt gesperrt.
- API-Fehler ⇒ `lockAll()` sperrt alle Bewegungs-, Jog- und Zubehör-Buttons.
- Firmware-Flash und Warteschlange leeren / Auftrag löschen nur nach `confirm()`.

## 8. Testen

```bash
python -m pytest tests -q                    # muss grün sein
```

Visuell ohne Maschine (Mock-Server, setzt Maschinenzustand künstlich – **nie auf dem Pi starten**):

```bash
LUMACUT_DATA=$(mktemp -d) PYTHONPATH=pi400 python tests/ui_mock_server.py idle 8101 &
LUMACUT_DATA=$(mktemp -d) PYTHONPATH=pi400 python tests/ui_mock_server.py running 8102 &
LUMACUT_DATA=$(mktemp -d) PYTHONPATH=pi400 python tests/ui_mock_server.py offline 8103 &
google-chrome --headless=new --hide-scrollbars --virtual-time-budget=5000 \
  --window-size=1440,1700 --screenshot=desktop.png http://127.0.0.1:8101/shot
google-chrome --headless=new --hide-scrollbars --virtual-time-budget=5000 \
  --window-size=820,2600 --screenshot=tablet.png http://127.0.0.1:8102/shot
```

`/shot` existiert nur im Mock (klickt automatisch „Motiv analysieren“; `?tab=diagnose` öffnet einen Tab).
Szenario `running` hält `machine.lock`, damit `busy`/`stale_ms` und das Veraltet-Banner sichtbar werden.

Manuell auf dem Pi: `http://<Pi-Adresse>:8080/` auf Tablet und Desktop öffnen,
Not-Aus-Bestätigung, Jog-Sperre ohne Homing, Rahmen fahren mit Laser **getrennt** prüfen.

## 9. Offene Punkte / TODO

- **Rahmen „hull“:** `/api/jobs/<f>/geometry` liefert nur Bounds. Für `mode=hull` bräuchte der Client
  Polygonpunkte (z. B. Feld `hull: [[x,y],…]` im Geometry-Endpoint). → Endpoint-Wunsch an `web.py`.
- **Platzierung / Nullpunkt:** `op=place`, `place_clear`, `origin_set`, `origin_clear`, `moveto` sind
  in der UI noch nicht verfügbar (Warteschlange reiht derzeit mit `origin=absolute` ein).
- **Kamera:** `/api/camera/snapshot` und `status.camera` werden noch nicht angezeigt.
- **Rahmen pro Queue-Eintrag:** wäre ein eigener Op oder `queue_frame` sinnvoll? → Machine Agent.
- Optional: Bett-Ansicht klickbar machen (Zielposition per `moveto`) – erst nach Sicherheitsreview.
- Optional: E2E-Browser-Test (Playwright ist auf der Box nicht installiert; derzeit nur Screenshot-Prüfung).

## 10. Phase 2 (2026-10-26): Nullpunkt oben rechts, Material-API, Phasen

**Koordinaten:** X0/Y0 oben rechts (Endschalter), +X → links, +Y → unten/Tür. API-Werte bleiben rohe Maschinen-mm.
- `#bedFlip` nutzt `translate(W,0) scale(-1,1)` (nur X gespiegelt); Texte liegen ungespiegelt in `#bedLabels`/`#bedAxes` (Bildschirm-x = W − x). Marker „0/0“ oben rechts, Pfeile „+X ←“, „+Y ↓“.
- Jog-Kreuz: links X+, rechts X−, oben Y−, unten Y+. Tastatur: ← X+, → X−, ↑ Y−, ↓ Y+.
- Safezone/Park/Probe-Punkte bleiben in Maschinen-mm im Flip-Group → erscheinen rechts/oben korrekt.
- Kamera/Bild-Overlays: aktuell keine Kamera-UI. Wenn ergänzt: ebenfalls horizontal spiegeln (`scale(-1,1)`), Texte außerhalb.

**Material (nur lesen, `GET /api/materials`):** `#materialSection` mit `#materialName`, `#materialThickness`, `#materialProcess` (Schneiden/Gravieren/Markieren), `#materialSettings` (Leistung % + S/255, mm/min + mm/s, Durchgänge = ceil(Dicke/Tiefe), Art, Zeilenabstand, Z je Durchgang), `#materialNote`, `#materialCompare` (liest `GET /api/jobs/<f>/content`, vergleicht häufigstes S/F der Laserbahnen), `#materialReload`, `#materialUnavailable`. Auswahl in `localStorage["lumacut.material"]`.
Fallback: `features` ohne `"materials"` oder GET-Fehler/404 → Picker ausgeblendet, Hinweis auf `update.sh`.

**Phasen:** `#phaseSteps` (home→probe→focus→job→park). Nutzt `s.phase`, falls vorhanden; sonst abgeleitet aus `job.state` + `job.probe` (probe done==total → Fokus).

**TODO / API-Lücken:** (1) kein Endpunkt/Feld, um ein Material auf Auftrag/Warteschlange anzuwenden (Vorschlag: `op=autorun material_id=…` bzw. Queue-Feld) – Werte werden weiterhin in Studio/Android in den G-Code gebacken. (2) kein Status-Feld `phase` (Park nicht erkennbar). (3) Material anlegen/ändern (POST/PUT mit `base_revision`, 409) nicht in der Pi-UI. (4) Machine Agent empfiehlt Not-Aus ohne `confirm()` + Auto-Retry – bewusst nicht umgesetzt.

**Tests/Mock:** `tests/test_pi_web_ui.py`; `tests/ui_mock_server.py` Szenarien `autorun`, `oldpi`, `/shot?material=…&thickness=…&process=…&compare=1`.
