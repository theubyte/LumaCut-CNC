# Materialtest mit Kamera

Der Pi kalibriert ein Material selbst, Schritt für Schritt mit der Kopfkamera
(`op=matcal`, Modul `pi400/marlin/matcal.py`). Starten über die Weboberfläche
(Einstellungen → „Material automatisch kalibrieren“) oder die App
(Kalibrieren → Je Material → „Automatisch mit Kamera“). Die Ergebnisse
speichert der Pi als Materialien; die Apps holen sie von dort.

## Ablauf

**Vorher:** referenzieren, Material wählen (Fahrhöhe), Kopf über eine freie,
glatte Stelle fahren – der Testbereich beginnt am Laserpunkt und wächst nach
+X/+Y der Maschine (Gravur 51 × 21 mm inklusive Anlauf, Schnitt 44 × 8 mm).
Hände raus, Deckel zu, Schutzbrille, Abluft.

**Gravur, Feld für Feld:**

1. Mitte des Testbereichs abtasten, Fokus daraus.
2. Ein 5 × 5-mm-Feld lasern (Zeilenabstand 0,1 mm, 3 mm Anlauf ohne Laser).
3. Kopf zur Fotoposition, Bild. Das neue Feld wird im Bild gesucht: Kamera und
   Laser liegen 1–2 mm auseinander, der Versatz wird beim ersten Feld gefunden.
4. Messen: **Ton** (0 = unberührt … 1 = schwarz, gegen das Material 1,4–2,4 mm
   daneben), **Fleckigkeit** (Streuung über 0,3 mm), **Streifen** (Streuung der
   Rasterzeilen), **Rauchrand** (Abdunklung 0,4–0,9 mm um das Feld).
5. Nächste Leistung: Sekante in log(Leistung) über alle bisherigen Felder
   (andere Tempi zählen mit gleicher Energie pro Fläche). Dunkel streifig →
   gleiche Energie langsamer; Rauchrand → schneller.
6. Ziele: Dunkel 0,85 · Mittel 0,55 · Hell 0,30, je ±0,06 und sauber. Höchstens
   4 Felder je Ton, 18 insgesamt; meist reichen 6–10.

7. **Zündgrenze:** Unter etwa 6 % zündet dieser Laser nicht sicher (gepunktete,
   unlesbare Schrift auf der Einladungskarte 2026-10-29: 6 % bei 3000 mm/min).
   Die Suche geht deshalb nie unter **8 %**: hellere Töne behalten die Energie
   (P/v) und werden schneller, höchstens 6000 mm/min.
8. Alle Felder des Laufs werden als **Schwärze-Kurve** (`tone_curve`) bei allen
   drei Gravur-Einträgen gespeichert.

**Schnitt, Durchgang für Durchgang:**

- Die Platte muss **hochgelegt** sein (Abstandhalter, ca. 10 mm Luft): nur dann
  fällt ein durchgeschnittenes Teil heraus und die Kamera sieht das Loch offen
  (Innen < halb so hell wie vorher). Flach auf der Opferplatte verkohlt die
  Rückseite, und die Ergebnisse streuen.
- Je Tempo (Standard 350, 500, 800, 1200 mm/min, 100 %) ein Durchgang, Foto,
  wieder ein Durchgang – bis das Loch offen ist. Fokus je Durchgang 0,4 mm
  tiefer (höchstens 3 mm).
- Ein Tempo, das schon 1,6 × die Energie des bisher besten braucht, hört auf.
- Gespeichert wird die Einstellung mit der **wenigsten Energie**
  (Durchgänge ÷ Tempo): am wenigsten Hitze durch das Holz, die sauberste
  Rückseite.

## Messungen Sperrholz 4 mm (2026-10-29, 10 W ohne Air Assist)

**Gravur** (bei 3000 mm/min, sofern nicht anders angegeben):

| Leistung | Ton | Bild |
| --- | --- | --- |
| 4,5 % | 0,34 | streifig (Laser flackert unter ca. 6 %) |
| 5,8 % | 0,46 | fleckig, Maserung schlägt durch |
| 6,0 % | 0,53 | fleckig |
| 6,3 % | 0,64 | fleckig |
| 7,7 % | 0,79 | gleichmäßig |
| 8,5 % | 0,87 | gleichmäßig |
| 10,6 % | 0,98 | schwarz, sauber |
| 12,8 % bei 4500 | 0,92 | **gleichmäßig, kein Rauchrand – gespeichert** |
| 14 % bei 6000 | 0,79 | streifig |
| 14 % bei 1500 | 1,00 | Rauchschatten um das Feld |

Mittel und Hell lagen anfangs bei 6 % / 3000 und 4,5 % / 3000 – unter der
Zündgrenze. Seit 2026-10-29 mit gleicher Energie: **Mittel 8 % / 4000**,
**Hell 8 % / 5300 mm/min** (ungefähr, nicht neu gemessen). Die Messwerte oben
liegen als Schwärze-Kurve bei den Sperrholz-Gravureinträgen.

Das Holz kippt zwischen 4,5 und 8,5 % von hell nach fast schwarz; Zwischentöne
sind fleckig. Raster (Dithering) mit der Schwarz-Einstellung: 50 % Punkte →
Ton 0,59, 36 % → 0,21, 26 % → 0,10 – nicht gleichmäßiger. Fokus 2 mm höher
macht Zwischentöne etwas gleichmäßiger (7,7 % → 0,72), 4 mm höher wieder
streifig.

**Schnitt** (100 %):

| Auflage | Ergebnis |
| --- | --- |
| flach auf der Opferplatte | 1×: nur 250 mm/min durch; 2×: 150/250/450 durch, 350 nicht; 3×: alle bis 450 durch – Rückseite stark verkohlt |
| hochgelegt (ca. 4 mm) | 350 × 2, **500 × 2**, 800 × 4, 1200 × 7 – genau bis das Teil fiel |

500 × 2 braucht die wenigste Energie und hatte laut Besitzer die sauberste
Rückseite → gespeichert. Viele schnelle Durchgänge (1200 × 7) brauchen bei
diesem Holz mehr Energie insgesamt.

## Regler in der App (Tempo und Leistung zusammen)

Im Ebenen-Fenster (Editor → Ebene antippen → „Abstimmen“):

- **präziser ↔ schneller** – für jede Ebene. Tempo und Leistung ändern sich im
  selben Verhältnis (gleiche Energie je mm, gleiche Schwärze). Langsamer gibt
  genauere Ecken und kleine Schrift. Der Regler hält an, wo die Leistung die
  Zündgrenze (8 % bzw. `min_power_pct`) oder 100 % erreicht, und im Tempo-Band
  der Kurve (`speed_min`..`speed_max`).
- **heller ↔ dunkler** – nur für Füll-Ebenen, deren Material eine Kurve hat.
  Der Ton folgt der Kurve über ln(P/v); ein anderer Zeilenabstand als bei der
  Messung wird umgerechnet (halber Abstand = halbe Energie je mm). Würde die
  Leistung unter 8 % fallen, wird stattdessen schneller graviert; geht auch
  das nicht mehr, sagt die App „Heller geht nicht“.

Beim Sperrholz liegt die Grenze für „präziser“ bei Dunkel (12,8 % / 4500) bei
etwa 2800 mm/min, darunter würde der Laser unter 8 % fallen.

## Grenzen

- Die Kamera regelt die Helligkeit selbst nach; gemessen wird deshalb immer
  gegen das Material im selben Bild.
- Glänzende, durchsichtige oder sehr dunkle Materialien: der Ton ist schlecht
  messbar, die Suche endet dann mit „nur ungefähr“.
- Kunststoffe: vorher mit dem Besitzer klären – schon S3 hat ein schwarzes
  Gehäuse angeschmolzen.
