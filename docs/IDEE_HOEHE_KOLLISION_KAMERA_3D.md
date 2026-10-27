# Idee: Fahrhöhe nach Material, Kollisionsschutz und 3D-Vorprüfung mit der Kamera

Stand: 2026-10-27. Status: **Idee, noch nichts gebaut.** Ergebnis eines Gesprächs mit dem Nutzer.
Hier steht alles, um später direkt weiterzumachen.

## 1. Ausgangsfrage

Bei hohen Objekten wie einer Zange, einem Gehäuse, einem Schraubendreher oder einem Eisstiel stellen sich mehrere Fragen:

- Woher weiß der Laser, wie hoch er zum Abtasten und Fotografieren fahren muss, ohne anzustoßen?
- Woher weiß er, dass der Taster überhaupt auf dem Objekt landet und nicht daneben?

## 2. Stand heute (Code vom 27.10., `06141e1`)

**Keine Fahrhöhe hängt vom gewählten Material ab.** Die Materialstärke berechnet nur die Zahl der Durchgänge (`materials.py`, `Design.kt effectivePasses`).

| Ablauf | Was passiert | Code |
|---|---|---|
| Referenzieren | `G28 X Y` in der **aktuellen** Höhe. Marlin hebt vorher fest auf 16 mm (`Z_HOMING_HEIGHT` = `Z_CLEARANCE_BETWEEN_PROBES` = 16). Dann `G28 Z` in der Ecke 0/0 und auf `z_clearance_mm` = **20 mm über dem Bett**. Einstellbar sind 0,5–50 mm, auf dem Pi unter „Sicherheitsrückzug nach Homing“ und in der App unter „Rückzug nach Homing“. | `transport.py safe_home`, `firmware/marlin/build.py` |
| Fahren / `move_to` | Z wird mindestens auf `clearance_mm` angehoben, nie abgesenkt. | `transport.py` |
| Abtasten G30 | Auf `max(Z, clearance)` über den Punkt, dann nach unten tasten. Danach auf `max(clearance, Kontakt + 2)`. | `transport.py probe_workpiece` |
| Abtasten im Auftrag | Ein Raster über das **Rechteck ums Motiv** (`heightmap.plan_probe`). Ist ein Punkt nicht erreichbar, wird ein Ersatzpunkt in der Nähe genommen (`nearest_reachable`). Innerhalb eines Bereichs wird auf den höchsten Kontakt + 3 mm gehüpft (`PROBE_HOP_MM`), zwischen den Bereichen auf `clearance`. Was unter dem Punkt liegt, wird **nicht** geprüft. | `heightmap.py`, `transport.py probe_surface` |
| Scan (App) | Kamerahöhe = gemessene Oberfläche + `aboveSurface` aus der Kalibrierung. Die Oberfläche kommt aus **einem** Punkt: dem letzten Abtastwert oder, falls es keinen gibt, der Mitte des ersten Scanbereichs. Ohne `aboveSurface` (alte Kalibrierung) wird fest auf `scanZ` gefahren. | `WorkspaceViewModel.scan / cameraOver` |
| Fokus | Z = Oberfläche + Fokusabstand 7 mm − Versatz Schalter→Laserspitze 1,5 mm. Auch die Leerfahrten im Motiv laufen in dieser Höhe. | `focus_compensation.py` |
| Parken | `max(Z, clearance, Oberfläche + 2)`, dann X0/Y0, danach 180 s Lüfter-Nachlauf. | `transport.py park_safezone` |

Die Kamera-Kalibrierung, die am 27.10. auf dem Pi gespeichert war (Revision 3), hatte **kein `aboveSurface`** und `scanZ = 20`. Sie stammt also nicht aus der automatischen Kalibrierung. Folge: Der Scan fährt fest auf Z 20, ohne abzutasten. Ein Objekt höher als etwa 18 mm würde getroffen.

## 3. Vorgaben des Nutzers

- **Die gewählte Materialstärke immer berücksichtigen.** Sonst droht eine Kollision.
- **Fahrhöhe H = Materialstärke + 20 mm.** Gemeint ist die Tasterspitze über dem Bett. Nach dem Referenzieren wird **noch in der Safezone** auf H gefahren, erst danach heraus zum Fotografieren und Arbeiten.
- **Die Kamerahöhe bestimmt die automatische Kamera-Kalibrierung**, nicht ein fester Wert vom Nutzer.
- **Flache Teile** wie eine MDF-Platte sollen ganz normal abgetastet werden.
- **Bei Objekten** soll die Kamera vorher erkennen, wo abtastbar ist, und auch die Höhe in 3D messen, aus mehreren Bildern und Höhen. Kalibrieren mit Markern ist erwünscht.

## 4. Geplanter Ablauf

### 4.1 Vor Scan und Start

- **Ohne gewähltes Material startet nichts.** Meldung: „Erst Material wählen – die Stärke bestimmt die Fahrhöhe“.
- **H = Stärke + 20 mm.**
- **Harte Obergrenze Z 80 mm** (Entscheidung des Nutzers, 27.10.). Gemeint ist die Tasterspitze über dem Bett. Diese Grenze darf keine Fahrt überschreiten, egal welcher Auftrag, Rückzug, Scan, Park oder welches Anheben vor dem Referenzieren.
  - **Grund:** Über 80 mm läuft der Laserkopf aus der Linearschiene der Z-Achse.
  - Für die Kamera selbst gilt keine Grenze. Die Fotohöhe wird aber über die Tasterhöhe gefahren (Oberfläche + Kamera-Abstand als Tasterspitze), und die muss unter 80 bleiben.
  - **Umgesetzt am 27.10.:** Firmware, Pi und App begrenzen auf 80 mm. Die Firmware wirkt erst nach dem Flashen. Vorher war Folgendes erlaubt:
    - Firmware: `Z_MAX_POS 90` (`firmware/marlin/build.py`).
    - Pi: `travels.z = 90` (`web.py`) und die Park-Prüfung `z_target > 90` (`transport.py`).
    - App: `Z_TOP = 85`. Die Schärfesuche der automatischen Kamera-Kalibrierung fährt bis Z 85, der Scan erlaubt bis `Z_TOP + 5` = 90 (`WorkspaceViewModel`). `PiApi` begrenzt `scan_z` auf 90.
  - Umsetzung: an allen drei Stellen auf 80. Die Firmware-Grenze wirkt erst nach dem Referenzieren. Vor dem Referenzieren begrenzt der Pi das Anheben anhand der gemerkten Höhe.
- **Daraus folgt die maximale Arbeitshöhe:** Materialstärke ≤ 80 − 20 = **60 mm**.
  - Die Kamera muss für den Scan auf Oberfläche + Kamera-Abstand. Ist dieser Abstand größer als 20 mm, sinkt die Grenze auf 80 − Kamera-Abstand. Beispiel: Kamera scharf bei 30 mm, dann maximal 50 mm Material.
  - Die App prüft das vorher: „Material zu hoch: maximal X mm mit dieser Kamera-Kalibrierung“.
- **Die App gibt H dem Pi mit**, je Auftrag oder Scan. Pi-Fahrten (`move_to`, Abtasten, Parken) nehmen dann `max(clearance, H)`.
- **Bei Objekten auf einer Platte** gilt bis zur Kamera-3D-Prüfung: die Objekthöhe als Stärke eintragen.

### 4.2 Referenzieren

1. **Vorher anheben.** Marlin kann die Höhe je Aufruf übernehmen (`G28 X Y R<H>`, Parameter R in `G28.cpp`, angehoben wird nur, nie abgesenkt, begrenzt auf `Z_MAX_POS`).
   - **Ist Z bekannt:** auf H anheben.
   - **Ist Z unbekannt:** Das gilt nur für den Moment *vor* dem Referenzieren, nachdem Marlin seine Position verloren hat. Das passiert nach Not-Aus (M112, danach ein SKR-Reset), nach Stromausfall, nach einem SKR-Neustart oder Firmware-Flash.
     - Z wird erst in der Ecke 0/0 referenziert. Die Fahrt in die Ecke geschieht also vorher, in einer Höhe, die Marlin nicht kennt.
     - Typischer Fall: Not-Aus mitten im Auftrag, der Kopf steht im Fokusabstand etwa 5 mm über dem Werkstück. Ohne Anheben fährt das Referenzieren quer über das Werkstück.
     - Marlin nimmt dann Z = 0 an. „Auf H anheben“ hieße blind um H nach oben. Steht der Kopf schon oben, fährt er gegen den oberen Anschlag; oben gibt es keinen Endschalter.
   - **Vorschlag dafür:** Der Pi merkt sich die letzte bekannte Z-Höhe dauerhaft, laufend aus M114. Bei unbekanntem Z hebt er relativ um `H − letzte Höhe` an, mindestens um 5 mm und nur so weit, dass oben Platz bleibt. Kennt er keine Höhe, weil der Kopf von Hand bewegt wurde oder die Datei fehlt, fragt die App: „Steht der Kopf über allem?“ **Bestätigung durch den Nutzer steht aus.**
2. X/Y in die Ecke, `G28 Z` in der Ecke 0/0. Dort liegt nichts, das ist die Safezone.
3. **In der Ecke auf H**, erst dann aus der Safezone heraus.

### 4.3 Scan (Arbeitsplatz, Motiv oder Markierung)

1. Auf H zum Scanbereich fahren.
2. Einen Abtastpunkt wählen. Bis zur Kamera-Prüfung (§5) ist das die Mitte des Bereichs. Dann langsam von H nach unten tasten.
3. **Messwert mit der Materialstärke vergleichen.** Weicht er um mehr als etwa 2 mm ab, anhalten: „Gemessen 12 mm, Material sagt 3 mm – falsches Material oder Objekt unter dem Taster?“
4. Für die Fotos auf Oberfläche + Kamera-Abstand fahren (§4.5) und Bild für Bild aufnehmen.
5. Danach zurück auf H oder in die Safezone parken.

### 4.4 Start

1. Prüfen, ob ein Material gewählt ist und das Motiv in der erlaubten Fläche liegt. Die Leistung kommt aus dem Material.
2. Referenzieren wie in §4.2.
3. Auf H zu den Abtastpunkten. Abtasten mit demselben Vergleich gegen die Stärke.
4. Innerhalb eines Bereichs mit dem Hüpfer (+3 mm) weiter, zwischen den Bereichen auf H.
5. Fokus: Oberfläche + 7 mm. Ab hier fährt der Kopf tief, auch bei Leerfahrten. Option: Bei getrennten Motivteilen längere Leerfahrten auf H.
6. Laserversorgung an (M106 P0), 800 ms warten, lasern, Laser aus.
7. Auf H hoch, dann erst in die Safezone parken. Lüfter 180 s nach.

### 4.5 Kamera-Abstand

- **Die automatische Kalibrierung gibt es schon** (`WorkspaceViewModel.autoCalibrate`, `focusSweep`): Punktraster lasern, abtasten, die Schärfe von Oberfläche **+ 8 mm** bis Z 85 in 5-mm-Schritten suchen, dann millimetergenau. Gespeichert wird `aboveSurface`.
- **Wo die Kamera scharf ist, legt das Objektiv fest.** Die App findet diese Höhe nur.
- **Entscheidung des Nutzers (27.10.):** Die Schärfesuche darf tiefer als die Fahrhöhe gehen. Zwischen Tasterspitze, dem tiefsten Punkt des Kopfs, und Werkstück bleiben aber **immer mindestens 5 mm**. Die Suche beginnt also bei Oberfläche **+ 5 mm** statt heute + 8 mm. Liegt die Schärfe am unteren Rand, meldet die App „Objektiv auf größeren Abstand drehen“. Diese Meldung gibt es schon (`CameraFocus.atEdge`). Die 20 mm gelten für Fahrten über unbekanntem Gelände. Die Fotohöhe liegt nur über einer gemessenen Fläche und darf darunter liegen, aber nie unter + 5 mm.
- **Erweiterung (optional):** In zwei Höhen kalibrieren. Dann lässt sich der Maßstab für jede Höhe rechnen, etwa für Fotos weiter über hohen Objekten.
- **Geometrie, geschätzt aus der alten Kalibrierung** (f ≈ 1101 px, rund 10,8 px/mm bei Z 20): Das Objektiv liegt etwa 100 mm über dem Material, also etwa 80 mm über der Tasterspitze.

## 5. Kamera-Vorprüfung: wo und wie hoch

Ziel ist, nur dort abzutasten, wo sicher Material liegt, die Höhe vorher grob zu kennen und erst dann zu fahren.

### 5.1 Objekt erkennen (2D)

- **Maske:** Den Scan mit dem leeren Bett oder der bekannten Plattenfarbe vergleichen, dazu Kanten auswerten. Das ergibt eine Maske „hier liegt etwas“.
- **Sicherer Bereich:** Die Maske um etwa 3 mm verkleinern (Tasterspitze plus Ungenauigkeit von Kamera und Mechanik, rund 0,15–0,2 mm). Abtastpunkte nur dort, möglichst unter dem Motiv. Ragt das Motiv über das Objekt hinaus, warnen.
- **Schwierig:** heller Eisstiel auf heller MDF (wenig Kontrast; Vergleichsscan oder dunkle Unterlage), glänzende oder durchsichtige Teile, sehr schmale Teile unter 6–8 mm.
- **Ausweg Antippen:** Der Nutzer tippt den Abtastpunkt im Scan an, die App prüft, ob er im sicheren Bereich liegt. **Das ist als erster, kleiner Schritt empfohlen.**

### 5.2 Höhe messen (3D)

1. **Stereo durch Bewegung:**
   - Ablauf: Foto, den Kopf bekannt verschieben (z. B. 20 mm), noch ein Foto. Aus der Verschiebung im Bild und der Lens-Kalibrierung ergibt sich die Höhe.
   - Genauigkeit, grob geschätzt: bei rund 100 mm Abstand deutlich unter 1 mm.
   - Aus 3–5 Bildern entsteht eine Höhenkarte.
   - Braucht Oberflächenstruktur.
2. **Laserpunkt als Messpunkt** (Triangulation wie bei 3D-Scannern):
   - Prinzip: Der Strahl geht senkrecht nach unten, die Kamera sieht ihn seitlich versetzt. Je höher die Oberfläche, desto weiter wandert der Punkt im Bild. Das funktioniert auch auf glatten Flächen.
   - **Laserpunkt im Kamerabild** (aus der Kalibrierung von Revision 3 gerechnet): etwa Pixel (944, 1030) von 1920 × 1080, also unten in der Mitte und nur rund 50 px über dem Rand. Das gilt für den Kalibrierabstand.
   - Empfindlichkeit grob 5 px pro mm Höhe.
   - Liegt die Oberfläche näher als etwa 10 mm unter dem Kalibrierabstand, wandert der Punkt aus dem Bild. Dann zum Messen höher fahren.
   - **Am Gerät noch nicht geprüft.** Prüfung ohne Laser: Den Laserpunkt über einen gebrannten Rasterpunkt fahren und ins Kamerabild schauen.
   - **Einschränkung:** Der Pi feuert nur während einer Bewegung (Inline-Modus `M3 I`). Ein stehendes `M3 S` ist gesperrt, also braucht es kurze, langsame Linien.
   - **Einschränkung:** Der LT-80W ist stark. Schon 1 % kann langsam auf dunklem Material markieren.
   - **Leistungstest** (Datei noch nicht erstellt):
     - Material: MDF und dunkle Pappe.
     - Linien: 10 mm lang, S1–S13 (0,4–5 %), je F120 und F1200.
     - Messen: ab welcher Linie die Kamera den Punkt sieht (A) und ab welcher Linie eine Spur bleibt (B). Nur wenn A deutlich unter B liegt, ist das brauchbar.
     - Nur mit Laserschutzbrille hinsehen.
   - **Alternative:** ein separater roter Kreuz- oder Linienlaser mit 5 mW am Kopf. Er markiert nichts, darf dauerhaft an sein und funktioniert nach dem Prinzip eines 3D-Scanners.
3. **Schärfe-Suche:** Z durchfahren, je Bildbereich die schärfste Höhe merken. Grob (±1 mm), reicht aber für Kollisionsschutz und Fahrhöhe. `CameraFocus.sharpness` gibt es schon.
4. **Kalibrierkörper:**
   - Der Laser graviert einen Stufenblock aus MDF-Lagen (0 / 3 / 6 / 9 / 12 mm) mit ArUco- oder AprilTag-Markern. Die sind besser als QR-Codes.
   - Die Kamera misst die Stufen, der Taster prüft nach. So wird die Höhenmessung kalibriert und kontrolliert.

### 5.3 Zusammengesetzt

1. Scan, Höhenkarte per Stereo; ohne Struktur per Laser- oder Linienlaser-Punkt.
2. **Alles flach** (Abweichung unter etwa 0,3 mm, Fläche deckt das Motiv): normal abtasten wie heute.
3. **Objekt erkannt:**
   - Fahrhöhe = Höhenkarte + 20 mm.
   - Nur auf sicheren, ebenen Stellen abtasten.
   - Bei Kollisionsgefahr vorher abbrechen.
   - Weicht ein Abtastwert stark von der Höhenkarte oder Stärke ab, warnen.
4. **Runde Teile:** Die Höhenkarte übernimmt die Fokusnachführung (`focus_compensation` mit `HeightMapSet`). Der Taster prüft nur 1–2 Punkte gegen. **Der Taster bleibt für den genauen Endwert zuständig.**

## 6. Reihenfolge (Vorschlag)

1. **Fahrhöhe aus der Materialstärke** (§4), dazu `G28 R`, der Abgleich Messwert ↔ Stärke und die Untergrenze + 5 mm für die Kamera-Suche. **Erst bauen, wenn die offenen Fragen in §7 geklärt sind.**
2. Abtastpunkt im Scan antippen, mit Prüfung gegen die Maske (§5.1).
3. Kalibrierkörper mit Markern (§5.2.4).
4. Stereo durch Bewegung: Höhenkarte, Flach-Erkennung, Kollisionsschutz.
5. Leistungstest Laserpunkt oder separater Linienlaser, danach Triangulation für glänzende und glatte Teile.
6. Höhenkarte für die Fokusnachführung bei runden Teilen.

## 7. Offene Fragen an den Nutzer

- Höhe vor dem Referenzieren, wenn Marlin die Position verloren hat (§4.2): Vorschlag „letzte Höhe merken“ bestätigen.
- ~~Untergrenze der Kamera-Schärfesuche~~: entschieden, mindestens 5 mm zwischen Tasterspitze und Werkstück (§4.5).
- Laserpunkt oder separater Linienlaser für die 3D-Messung: Entscheidung nach dem Leistungstest.

Vor dem Bauen: `git fetch` und die letzten Commits sowie `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` prüfen. Andere Sitzungen arbeiten parallel an Kamera, Kalibrierung und Pi.
