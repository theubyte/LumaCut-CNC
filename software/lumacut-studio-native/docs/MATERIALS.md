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
