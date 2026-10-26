# Materialbibliothek (`src/lumacut_materials/`)

Startwerte für Diodenlaser: Material + Dicke + Operation → Leistung,
Geschwindigkeit, Durchgänge, Tiefe je Durchgang und Fokus-Absenkung (Z) je
Durchgang. Der Kern ist reines Python (kein Qt); nur `dialog.py` nutzt PySide6.

> **Alle Werte sind Startpunkte**, abgeleitet aus Herstellertabellen und
> Community-Daten, **nicht an der Maschine gemessen**. Immer zuerst mit dem
> Materialtest (*Auftrag → Materialtest…*) auf einem Reststück prüfen.

## Bedienung

*Material → Materialbibliothek …* (Strg+Umschalt+M):

1. Material, Dicke (editierbar, z. B. `4.5`), Operation und Laser wählen.
2. Die Zusammenfassung zeigt Leistung, mm/min, Durchgänge, Tiefe/Durchgang,
   Fokus je Durchgang und ggf. einen empfohlenen Fokus-Start.
3. **Auf aktive Ebene anwenden** setzt `power`, `speed`, `passes`,
   `z_step` (und `line_interval` bei Gravuren) – ein Undo-Schritt.
4. **Als Preset speichern…** legt eigene Werte in
   `%APPDATA%/LumaCut Studio/material_presets.json` (QStandardPaths) ab.
5. **Relief aus Bild…** (nur Operation *3D-Relief*): Graustufenbild
   (weiß = hoch, schwarz = tief) → G-Code an die Maschine senden (ohne Start)
   oder als Datei speichern.

6. **Auf Bild (3D-Tiefe)** (nur *3D-Relief*): übernimmt den Reliefplan in die
   gewählten Bildobjekte (Modus `depth3d`, s. „Relief und 3D-Tiefe“).
7. **Testzelle als Preset…**: siehe „Materialtest → Preset“.

Schnellzugriff im Hauptfenster: das Feld *Design → Material* (bisher leer) ist
jetzt die Bibliothek mit Dicke, Operation, „verknüpfen“ und *Auf aktive Ebene*;
die Statuszeile zeigt „Material (verknüpft/zugewiesen)“ der aktiven Ebene.

## Verknüpfen vs. Zuweisen (Ebene ↔ Bibliothek)

Wie LightBurn *Link* / *Assign*. Die Ebene speichert `material_ref`
(`lib:<material>/<operation>/<laser>`) und `material_link` (beide nur in der
Datei, wenn gesetzt).

* **Verknüpft** (Standard bei Bibliothekswerten, Häkchen „verknüpfen“): Ändert
  man an der Ebene die **Dicke** (Schneiden) bzw. **Zieltiefe/Dicke**
  (Gravur/Relief), plant die Bibliothek Leistung, Geschwindigkeit,
  Durchgänge, Z-Absenkung, Tiefe je Durchgang und Kerf/Stegbreite neu – im
  **selben Undo-Schritt** wie die Dickenänderung (egal ob aus Ebenen-Panel,
  Dialog oder Skript).
* Von Hand geänderte Leistung/Geschwindigkeit/Durchgänge/Z/Tiefe je Durchgang
  **lösen** die Verknüpfung (Werte bleiben, Status „zugewiesen“). Anderes
  Material eintragen entfernt den Bezug. Nicht planbare Werte (z. B. Dicke
  außerhalb des Modells) lösen ebenfalls.
* **Zugewiesen**: Werte werden einmalig kopiert. Eigene Presets (auch aus dem
  Materialtest) werden immer nur zugewiesen – sonst würden gemessene Werte
  bei der nächsten Dickenänderung überschrieben.

Technik: `lumacut_canvas.commands.register_layer_attr_hook` – ein generischer
Hook liefert zu einer Ebenen-Änderung abgeleitete Attribute, die
`SetLayerAttr(s)Command` mit in den Undo-Schritt nimmt
(`lumacut_materials.link.install_link_hook`).

## Materialtest → Preset

1. *Auftrag → Materialtest…* erzeugt das Raster (eine Ebene je Zelle,
   „Test P…% F…“). Nach dem Lasern die beste Zelle auswählen (aktive Ebene).
2. *Material → Testzelle als Preset speichern …* (oder im Dialog
   **Testzelle als Preset…**): Material/Dicke/Operation/Laser aus dem Dialog,
   Leistung/Geschwindigkeit/Durchgänge/Z aus der Zelle, Zeilenabstand und
   Hinweise aus der Bibliothek. Ist keine Testzelle aktiv, fragt der Dialog
   nach der Zelle.
3. Das Preset (`source: "test"`) erscheint unter „Gespeichert“ und im
   Preset-Menü des Ebenen-Panels.

API: `lumacut_materials.testgrid.preset_from_test_cell(db, layer, material_id, op, thickness)`.

## Kerf, Haltestege, Anfahrt

Jedes schneidbare Material hat einen `process`-Block (Schätzung, `status:
"estimate"`): Schnittbreite = Basis · √(Spot/0,08) + k · Dicke, Stegbreite,
Stegabstand, Anfahrt (`process.py`). Beim Anwenden *Schneiden* setzt die
Bibliothek an der Ebene (Felder aus `lumacut_job.cutpath`):

* `kerf_mm` = **halbe** Schnittbreite (Versatz zur Abfallseite),
* `tab_width_mm`,
* `tab_spacing_mm` und `lead_in_mm` **nur, wenn bereits > 0** – sie schalten
  Stege/Anfahrt ein, das bleibt Entscheidung des Nutzers.

Bei verknüpften Ebenen werden Kerf/Stegbreite mit der Dicke neu gesetzt,
außer sie wurden von Hand geändert (z. B. nachgemessener Kerf). Kerf immer mit
einem Testquadrat nachmessen: (Soll − Ist) / 2 = Versatz.

## Relief und 3D-Tiefe

Zwei Wege, ein Schichtplan (`planner.plan_relief`):

| | `relief.py` (Relief aus Bild…) | Bild-Modus `depth3d` (`raster.sliced_depth_gcode`) |
|---|---|---|
| Leistung | variabel je Pixel, gleiche Schichten | konstant, tiefe Pixel in mehr Schichten |
| Ausgabe | eigene G-Code-Datei / an Maschine | Teil des Canvas-Auftrags (Bildobjekt) |
| Fokus | Z je Schicht | Z je Stufe (`z_step_mm`), Summe ≤ 3 mm |

`depth3d.depth3d_image_settings(db, material, Tiefe)` liefert die
`ImageSettings` (Stufen = Reliefschichten, Leistung, mm/min, Zeilenabstand,
Z je Stufe), damit beide Wege dieselbe Gesamttiefe ergeben.

Nicht laserbare Materialien (PVC/Kunstleder, PC, ABS, klares/weißes/blaues
Acryl, PTFE, POM, Glasfaser, Carbon, Chromleder, Metall schneiden, …) stehen
mit ✕ am Ende der Liste und zeigen nur die Warnung (z. B. Chlorgas, giftige
Dämpfe, Brand, Laser wird transmittiert).

## Laser

| ID | optische Leistung | Hinweis |
|---|---|---|
| `lasertree_lt80w_aa_pro` (Standard) | 10 W | „80 W“ = elektrische Eingangsleistung; 450 nm, Spot 0,08 mm, Air Assist |
| `diode_5w`, `diode_10w`, `diode_20w`, `diode_40w` | 5/10/20/40 W | generische Profile |

## Modell

Tiefe je Durchgang: `d = d_ref · (E/E_ref)^0.8 · (P_eff/P_eff_ref)^0.3`
mit Energie je Strecke `E = P_eff / v` (Schnitt) bzw. `P_eff / (v · Zeilenabstand)`
(Gravur), `P_eff = P_optisch · Leistung%`. Referenzpunkte stammen pro Material
aus Hersteller-/Community-Tabellen (siehe `sources` in `materials.json`).

**Schnitt:** Zieltiefe = Dicke · 1,1; maximale Tiefe je Durchgang ist durch
eine Mindestgeschwindigkeit (Wärmeeintrag/Verkohlung) und eine
Material-Obergrenze begrenzt; Durchgänge = ⌈Ziel / d_max⌉; Geschwindigkeit
wird auf 10 mm/min abgerundet, bei > 6000 mm/min wird stattdessen die Leistung
gesenkt. Fokus-Absenkung je Durchgang ≈ 0,7 · Tiefe/Durchgang (≤ 2 mm,
Summe ≤ 3 mm), ab 4 mm Dicke zusätzlich empfohlener Fokus-Start
`−min(2, 0,25·Dicke)` mm (nur Hinweis – der Pi fokussiert vor dem ersten
Schnitt selbst auf Oberfläche + 5,5 mm).

**Gravur:** `engrave_surface` (Oberfläche, konstante Energie),
`engrave_shallow` 0,15 mm, `engrave_medium` 0,4 mm, `engrave_deep` 1,0 mm –
mehr Durchgänge, sobald die Geschwindigkeit unter 300 mm/min fiele.

**3D-Relief:** Schichten zu ≈ 0,25 mm (LT-80W), 2…60 Schichten, Fokus-Absenkung
ab 1 mm Tiefe, Abschluss-Durchgang mit doppelter Geschwindigkeit/30 % Leistung.

Beispiele LT-80W (Schnitt, Luft an):

| Material | mm | % | mm/min | Durchg. | mm/Durchg. | Z/Durchg. | Fokus-Start |
|---|---|---|---|---|---|---|---|
| Pappel-/Linden-Sperrholz | 1 | 100 | 420 | 1 | 1,10 | – | – |
| Pappel-/Linden-Sperrholz | 3 | 100 | 250 | 2 | 1,65 | 1,04 | – |
| Pappel-/Linden-Sperrholz | 5 | 100 | 220 | 3 | 1,83 | 1,16 | −1,25 |
| MDF | 3 | 100 | 200 | 2 | 1,65 | 1,04 | – |
| Acryl schwarz | 3 | 100 | 80 | 2 | 1,65 | 1,04 | – |
| Acryl schwarz | 5 | 100 | 70 | 3 | 1,83 | 1,16 | −1,25 |

## Relief-G-Code

`relief_to_gcode(job)` erzeugt pro Schicht eine Serpentinen-Rasterung
(abwechselnd X/Y), Overscan als `G1 … S0` (auf die Arbeitsfläche begrenzt),
Lücken ≥ 1 mm per `G0`, Leistung je Zelle in 16 Stufen. Standard-Flavor
`marlin_inline` = `M3 I` + `S` in jeder `G1`-Zeile (Marlin Inline-Laser – das
Pendant zu GRBL-M4, das der Pi-`MarlinLaserGuard` ablehnt). Zwischen Schichten
`G91 / G0 Z-… / G90`, am Ende Rückstellung. Alle Tests prüfen den G-Code gegen
den echten Pi-Guard (`tests/_pi_guard.py`). `flavor="grbl_m4"` nur für andere
Maschinen.

Höhenkarte (`heightmap.py`): Alpha → weiß, Invertieren, Helligkeit, Kontrast,
Gamma, Flächen-/linear-Resampling auf den Zeilenabstand, Gauß-Glättung.

## Materialdatenbank auf dem Pi

Der Pi ist die gemeinsame Quelle für Studio, Android und Pi-Web (Anforderungen
`docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §4, Vertrag
`docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` §3). Studio-Seite:

- `remote.HttpMaterialsTransport` – urllib, kein Proxy, keine Umleitungen,
  `X-LumaCut-Key` falls gesetzt. Erkennt die Server-Variante an `GET /api/materials`
  (auch vor dem ersten Schreiben): **Liste** (`{"revision", "materials"}`, Schreiben mit
  `base_revision`, 409) – das ist der echte Pi (`pi400/marlin/materials.py`,
  `PI_API_REFERENZ.md` §4.14) – oder, als Rückfall, **Datenbank + Presets** (`{"db"}` mit
  ETag/304, `/api/materials/presets/<id>` mit `If-Match`). 404/405 = Pi ohne Material-API;
  PUT-404 in der Liste = inzwischen gelöscht (Konflikt).
  Fehler: `MaterialsOffline`, `MaterialsUnsupported` (`MaterialsNoDatabase`),
  `MaterialsConflict`, `MaterialsError` (400 mit Grund aus `{"error"}`).
- `sync.MaterialSync(ordner, preset_pfad)` – Qt-frei, thread-sicher:
  `db()` (Pi-Kopie oder mitgeliefert), `refresh(transport)` → `SyncResult`
  (`source` pi/cache/bundled, `online`, `db_changed`, `presets_changed`, `uploaded`,
  `conflicts`, `rejected`, `message`), `save_preset(p, transport|None)` →
  `"pi"`/`"pending"`/`"rejected"` (Pi lehnt ab, Grund in `last_message`, bleibt ausstehend),
  `delete_preset(name, transport|None)`, `resolve_conflict(conflict, "mine"|"pi", t)`.
- Dateien im App-Datenordner (`LUMACUT_MATERIALS_DIR` überschreibt):
  `material_presets.json` (wie bisher, Presets jetzt mit `id`),
  `materials_pi_cache.json` (`format: lumacut-materials-cache`, `etag`, `version`,
  `fetched_at`, `db`), `material_sync.json` (`etags`, `base` = Inhalts-Fingerabdruck
  je ID, `pending`, `deleted`).
- Preset-ID: `preset_id(name)` = `<slug>-<6 hex sha1>` – gleicher Name, gleiche ID auf
  allen Geräten; vergibt der Pi eigene IDs (POST), übernimmt Studio sie.
- Abgleichregeln: Pi gewinnt; offline Geändertes wird hochgeladen, wenn der Eintrag auf
  dem Pi unverändert ist, sonst bleibt die eigene Fassung als „<Name> (lokal)“; auf dem
  Pi Gelöschtes verschwindet lokal; alte Presets ohne ID werden hochgeladen.
- Studio (`dialog.MaterialTools`): Abgleich beim Verbinden im Hintergrund-Thread (ohne
  Qt-Objekte, Ergebnis per Timer im GUI-Thread), `MaterialDB.replace()` tauscht die
  Datenbank an Ort und Stelle, Schnellfeld/Dialog/Ebenen-Panel laden neu.
- Abbildung Preset ↔ Pi-Material (Liste): `remote.preset_to_material` /
  `material_to_preset` (`cut` ↔ `Schneiden/line`, `engrave_surface` ↔ `Markieren`,
  andere Gravuren ↔ `Gravieren/fill`, `line_interval_mm` ↔ `interval_mm`). Studio-Zusatzfelder
  (`material_id`, `op`, `laser_id`, …) speichert der Pi unverändert; passt `op` nicht mehr zu
  `process` (von Android/Pi-Web geändert), gilt `process`. Zahlen werden auf die Pi-Bereiche
  begrenzt (`remote.PI_LIMITS`), leere Werte weggelassen; gleiche Namen vom Pi bekommen die
  Operation angehängt.
- Tests: `tests/test_materials_sync.py` mit `tests/fake_materials_pi.py` (beide Varianten,
  „list“ prüft wie der Pi) und `tests/test_materials_pi_real.py` gegen den echten
  `pi400/marlin/web.py` im Testprozess (ohne Flask übersprungen).

## API (ohne Qt)

```python
from lumacut_materials import load_db, plan, make_preset, PresetStore
db = load_db()
p = plan(db, "basswood_plywood", "cut", 5)            # LT-80W
p.passes, p.speed_mm_min, p.power_pct, p.z_step_mm, p.focus_offsets_mm
preset = make_preset(db, "mdf", "engrave_deep", laser_id="diode_20w")
```

Neu erzeugen nach Änderungen am Modell: `python -m lumacut_materials.build`
(im Ordner `src`) schreibt die flachen Tabellen (`settings[]`) in `materials.json`.

Neues Layer-Feld `z_step` (Fokus-Absenkung je Durchgang, 0…2 mm, Summe ≤ 3 mm):
`gcode.py` senkt Z zwischen den Durchgängen relativ ab und stellt nach der
Ebene wieder her.
