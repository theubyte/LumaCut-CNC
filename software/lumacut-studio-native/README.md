# LumaCut Studio (Native)

Professionelle Windows-Desktop-App für die LumaCut-Maschine.

- Geschrieben in Python mit PySide6 (Qt)
- Kein Web-UI, echte native Fenster
- Arbeitsfläche 360 × 340 mm (Safezone intern und unsichtbar)
- Scan & Probe Workflow vorbereitet
- Direkte Anbindung an die Pi-API (Status, Home/Jog/Park/Fokus, Not-Aus, Aufträge)

## Starten
```bash
pip install -r requirements.txt
python src/main.py
```

## Bauen (Windows)
`build-windows.bat` (installiert Abhängigkeiten und baut) oder:
```bash
pip install -r requirements.txt pyinstaller
python build_exe.py
```
`build_exe.py` enthält die PyInstaller-Optionen (alle eigenen Pakete, `materials.json`,
ezdxf/svgelements/pypdf/shapely) – dieselben nutzt die CI – und bricht ab, wenn die
Materialdaten im Ergebnis `dist/LumaCutStudio/` fehlen (`python build_exe.py --check` prüft nur).

## Hauptansicht: Material · Design · Start

Siehe `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §1/§3. Rechts stehen drei
große Knöpfe (≥ 48 px, touchtauglich) – das reicht für den normalen Auftrag:

1. **Material** – die *eine* Materialwahl wie in der Android-App: große Liste
   „Material · Dicke“ mit Suche direkt darunter (Pi-Datenbank, ohne Pi die
   zuletzt gespeicherte/mitgelieferte Liste). Ein Tipp setzt Leistung, Tempo und
   Durchgänge aller Ebenen (Schneiden bzw. Gravieren je Ebene, ein Undo-Schritt).
   Die Ebenenliste zeigt nur das Ergebnis; Materialwerte bearbeiten
   (Bibliotheksdialog, Testzelle, Pi-Abgleich) liegt unter „Mehr“
   (Anforderungen §9.1, `lumacut_canvas/material_picker.py`).
2. **Design** – Menü: Importieren …, Text, Rechteck, Ellipse, Polygon, Freihand, Linie.
3. **Start** – Ein-Klick-Auftrag: baut den G-Code wie „Design senden“
   (inkl. „Nur Auswahl“ und Fokuskorrektur), lädt ihn hoch und startet den
   automatischen Ablauf der Maschine (Pi `op=autorun`: Referenzfahrt → Abtasten
   → Fokus → Auftrag → Parken). Vorher fragt die Maschine einmal nach.
   *Hook:* Ein Höhenmesh fährt der Pi im Ein-Klick-Ablauf noch nicht (nur ein
   Abtastpunkt); umstellen in `lumacut_canvas/main_view.py` (`START_HOOK`).

Daneben: **Kamera-Scan** (optional, `ScanPanel.start_scan`, ändert den Auftrag
nicht) und **Verbinden** (nur sichtbar, solange keine Verbindung besteht).

**Mehr ▸** (standardmäßig zu) blendet alles Erweiterte ein: Ablauf, Scan &
Probe, Maschine (Adresse, Joggen, Homing, Abtasten, Fokus, Rahmen …),
„Manuell senden“ (Design senden / hochgeladenen Auftrag starten), die
Werkzeugleiste „Auftrag“ (Schnittoptionen mit Kerf, Haltestege, Anfahrt, Überschnitt, Perforation;
Rahmen, Zeit, Materialtest …) sowie in der Ebenenliste Leistung/Tempo/Durchgänge
und Füllung. Die Auftrags-Aktionen sind zusätzlich im Menü **Auftrag** und über
ihre Tastenkürzel erreichbar, auch wenn „Mehr“ zu ist. NOT-AUS bleibt immer
oben in der Leiste.

## Arbeitsfläche (Canvas)

Code: `src/lumacut_canvas/` (eigenes Paket, Modell ohne Qt-Abhängigkeit).
Eigenständig testen: `python src/canvas_demo.py`.

### Koordinaten: Nullpunkt oben rechts

Die Maschine homt **oben rechts**: X0 Y0 liegt dort, **+X fährt nach links**, **+Y nach vorne zur Tür**
(`docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §2.1, §2.3). Umgerechnet wird nur in
`lumacut_canvas/workarea.py`; der Schalter ist `ORIGIN_TOP_RIGHT`.

| Art | Wo | Ursprung / Richtung | Umrechnung |
|---|---|---|---|
| Bildschirm | Dokument, Szene, Overlays, SVG/PNG, `.lumacut.json` | oben links, x → rechts, y ↓ | – (Szene ungespiegelt, Text lesbar) |
| Anzeige | Lineale, Statusleiste, X/Y-Felder | oben rechts, X ← links, Y ↓ | `screen_to_user(x, y) = (360 − x, y)` |
| Maschine | G-Code, Rahmen, Schätzung, Raster/Bilder | oben rechts + 30-mm-Safezone | `screen_to_machine(x, y) = (390 − x, 30 + y)` |

- X-Feld der Eigenschaftsleiste = Abstand der **rechten** Kante vom Nullpunkt (`user_x_of`).
- `to_machine`/`from_machine` sind Aliase für `screen_to_machine`/`machine_to_screen` (Eingabe in Bildschirm-mm).
  Rechtecke aus zwei Ecken immer über `machine_rect_to_screen()` oder mit `min`/`max` bilden.
- Bilder in Maschinenrichtung (Kameramosaik, Höhenkarte: Spalte 0 = kleinstes Maschinen-X) für den
  Bildschirm waagerecht spiegeln (`IMAGE_FLIP_X`).
- Dateien speichern Bildschirm-mm und das Feld `"coords": "screen-tl/machine-tr-v2"`. Alte Dateien ohne Feld
  liegen an derselben sichtbaren Stelle; unbekannte Werte werden abgelehnt.

- **Werkzeuge:** Auswahl (V), Rechteck (R), Ellipse (E), Linie (L), Polygon (P), Freihand (F), Text (T).
  *Umschalt* beim Zeichnen = Quadrat/Kreis/45°-Linie; Klick ohne Ziehen legt
  ein 20-mm-Objekt an. Doppelklick auf Text = Text ändern. Polygon: Klick = Punkt,
  Doppelklick/Enter oder Klick auf den ersten Punkt = schließen, Rücktaste = Punkt weg.
  Freihand: ziehen zeichnet einen offenen Pfad (ohne Raster); beim Loslassen wird er mit
  Ramer-Douglas-Peucker vereinfacht (Toleranz 0,2 mm, `tools.FREEHAND_TOLERANCE_MM`), Esc bricht ab.
- **Bearbeiten:** Verschieben (Maus oder Pfeiltasten 1 mm, *Umschalt* 10 mm),
  Skalieren über 8 Griffe (*Umschalt* = Seitenverhältnis halten), Entf,
  Strg+D duplizieren, Strg+C/V, Strg+Z/Strg+Y, X/Y/B/H in mm in der Eigenschaftsleiste.
- **Drehen:** runder Griff über dem Auswahlrahmen (*Umschalt* = 15°-Schritte),
  Feld „Winkel“ in der Eigenschaftsleiste, Strg+R / Strg+Umschalt+R = ±90°.
  Gedrehte Objekte lassen sich weiter verschieben und entlang ihrer Kanten skalieren;
  Drehung wirkt in Datei, SVG/PNG-Export und G-Code.
- **Glatte Kreise/Ellipsen:** Anzeige und SVG-Export nutzen echte Kurven (8 Bézierbögen,
  Formfehler ≤ 0,001 mm bei Ø 360 mm). G-Code, Schraffur-Beschnitt und Boole/Versatz zerlegen
  über `shape_paths.shape_polygons` mit Sehnenfehler **≤ 0,02 mm** (Ellipse analytisch,
  ≥ 64 Segmente, Ø 360 mm ≈ 212). Nur G1-Geraden, kein G2/G3 (Höhenausgleich und Analyse auf
  dem Pi lehnen Bögen ab). Siehe Anforderungen §9.3.
- **Gruppen:** Strg+G gruppiert, Strg+Umschalt+G löst eine Ebene der Gruppierung
  (verschachtelte Gruppen möglich). Ein Klick wählt immer die ganze Gruppe;
  Verschieben, Skalieren, Drehen, Löschen und Duplizieren wirken auf die Gruppe.
  Gruppenmitglieder bleiben auf ihren Ebenen (Laserparameter je Ebene).
- **Ansicht:** Mausrad = Zoom (ohne Auswahl um den Cursor, mit Auswahl auf die
  Auswahlmitte zu – sie bleibt stehen bzw. wird zentriert; 0,4–60 px/mm), mittlere Maustaste oder Leertaste+Ziehen = Verschieben,
  Strg+0 = Fläche einpassen, Raster und Fangen (1 mm) umschaltbar, Lineale in mm,
  Cursorposition in mm in der Statusleiste.
- **Touch (z. B. Surface Pro):** „Touch-Modus“ in der Canvas-Aktionsleiste. Er schaltet
  sich bei einem Touchscreen, auf kleinen Bildschirmen (< 1500 × 950 logische px, z. B.
  Surface Pro mit 150–200 % Skalierung) oder beim ersten Fingertipp selbst ein; eine manuelle Wahl wird in QSettings (`canvas/touch_mode`) gespeichert und
  hat dann Vorrang. Im Touch-Modus (Werte in `lumacut_canvas/touch.py`, `TouchMetrics`):
  - Griffe 18 px gezeichnet, Trefferfläche 44 × 44 px, Dreh-Griff 48 px über dem Rahmen;
    konstant in Bildschirm-Pixeln bei jedem Zoom (Maus-Modus unverändert 9 px). Bei kleinen
    Objekten bleibt die Mitte frei zum Verschieben (die Griff-Fläche reicht innen nur bis
    ¼ der kürzeren Seite).
  - Fangbereich für Objekte 12 px statt 5 px. Liegen mehrere Objekte darin, gewinnt ein
    Treffer auf dem Umriss (bzw. im Text/Bild) vor einem Treffer nur im Inneren, dann das
    kleinere Objekt, dann das oberste – so bleibt eine dünne Linie auf/unter einer Fläche greifbar.
  - Zwei Finger: Pinch-Zoom um die Fingermitte (0,4–60 px/mm) und gleichzeitig Verschieben;
    Lineale und Raster laufen mit. Ein laufendes Verschieben/Skalieren wird beim zweiten
    Finger abgebrochen (nichts verrutscht).
  - Ein Finger: auf einem Objekt/Griff wie die Maus (verschieben, skalieren, drehen,
    zeichnen); mit dem Auswahl-Werkzeug auf leerer Fläche = Ansicht verschieben. Tippen =
    Klick (leere Fläche: Auswahl aufheben), Doppeltippen = Doppelklick.
    Ein Gummiband-Rahmen geht nur mit Maus oder Stift.
  - Langes Drücken (0,55 s, ohne Bewegen) öffnet das Kontextmenü (wie Rechtsklick):
    Kopieren, Duplizieren, Löschen, Drehen, Gruppieren, Auswahl einpassen, Einfügen,
    Alles auswählen, Pfadvorschau – im Touch-Modus mit ≥ 44 px hohen Zeilen. Das
    Windows-„Gedrückt halten = Rechtsklick“ öffnet es nicht ein zweites Mal.
  - Zoom-Knöpfe unten rechts im Canvas (−, +, Einpassen, 100 %), 52 px.
  - Werkzeugleisten mit 32-px-Icons in ≥ 48-px-Knöpfen; im Ebenen-Panel 56 px hohe Zeilen,
    ≥ 40-px-Knöpfe und 34 px hohe Eingabefelder.
- **Kleine Bildschirme** (`lumacut_canvas/fit.py`): Die senkrechte Werkzeugleiste hat immer
  ≥ 44 × 44-px-Knöpfe mit Abstand. Das Fenster startet in der Größe des verfügbaren
  Bildschirms (max. 1400 × 900) und wird zentriert; die Mindestgröße wird nie größer als der
  Bildschirm. Eigenschaftsleiste über dem Canvas scrollt waagerecht statt Felder
  abzuschneiden; Ebenen-Panel und rechte Seitenleiste scrollen senkrecht (auch per Finger)
  und bekommen beim Öffnen die Breite, die ihr Inhalt braucht (höchstens 26 % bzw. 42 % der
  Fensterbreite, sonst zusätzlich waagerechter Bildlauf). Formulare im Ebenen-Panel brechen
  bei schmaler Breite unter die Beschriftung um. Die rechte Seitenleiste wird generisch
  kompakt gemacht (`compact_sidebar`, ohne die Panels selbst zu ändern): schmaleres
  Knopf-Polster (Höhe bleibt 40 px), Formularzeilen brechen um, Knopfreihen mit ≥ 3
  Knöpfen über 340 px werden zweispaltig, breite Auswahllisten schmal (aufgeklappt
  weiterhin volle Breite). So passt sie bei 1024 × 600, 1280 × 720 und 1368 × 912 ohne
  Seitwärts-Scrollen (Test `test_small_screen.py`, auch auf Windows-CI).
  - Vom System aus Touch erzeugte Maus-Ereignisse werden während und 0,6 s nach einer
    Berührung ignoriert (keine doppelte Ausführung); Touchpad-Gesten bleiben beim System.
- **Ebenen:** Farbe, Name, sichtbar, gesperrt, Reihenfolge; je Ebene
  Leistung (1–100 %), Geschwindigkeit (1–6000 mm/min) und Durchgänge (1–30),
  optional Material/Dicke/Tiefe je Durchgang (siehe „Material-Grundlage“).
  Objekte übernehmen Farbe und Parameter ihrer Ebene. Ausgeblendete Ebenen
  werden nicht gelasert; die unterste Ebene läuft zuerst.
- **Dateien:** Speichern/Öffnen als `*.lumacut.json` (Format `lumacut-canvas`, v3, mm;
  v1/v2-Dateien werden weiter gelesen; Material-Felder werden nur gespeichert, wenn gesetzt),
  Export als SVG oder PNG (Strg+E).
- **An die Maschine:** „Design senden“ (Toolbar) erzeugt Marlin-G-Code
  (`lumacut_canvas/gcode.py`, Regeln wie `marlin-postprocessor.mjs`) und lädt
  ihn über das Maschinen-Panel hoch; gestartet wird erst mit „Start Job“.
- **Park-Ecke prüfen:** Vor jedem Senden (Design, Ablauf, Relief, Verlauf) und vor „Start“
  prüft Studio wie der Pi, ob der Laser-an-Bereich in die Park-Ecke reicht (Kopf v6:
  X0–78 / Y0–35 mm, vom Pi-Status `park_corner_mm` gelesen, sonst Standardwert). Absolut
  betroffen → nicht gesendet; Start am gewählten Ursprung betroffen → nicht gestartet bzw.
  Hinweis nach dem Senden – jeweils mit der nötigen Verschiebung in mm (X+ = nach links,
  Y+ = nach unten). Auch die Zeitschätzung (*Alt+P*) nennt das Problem.
  Code: `src/lumacut_job/park_corner.py`.
- **Rahmen:** „Rahmen“ (*Strg+Umschalt+F*, Rechteck) bzw. „Gummiband-Rahmen“
  (*Alt+Umschalt+F*, konvexe Hülle) oder der Knopf „Rahmen“ im Maschinen-Panel
  fahren den Umriss mit ausgeschaltetem Laser ab (`op=frame`). Der gesendete
  Auftrag bleibt geladen: senden → Rahmen → starten, ohne neu zu senden.
- **Schnittoptionen je Ebene** („Schnittoptionen…“, *Alt+K*, aktive Ebene, ein Undo-Schritt;
  wirken beim Senden, Schätzen, Rahmen und „G-Code speichern“; alles außer der Perforation nur auf
  geschlossene Konturen):
  - *Kerf-Versatz* (`kerf_mm`, −2…2 mm): positiv verschiebt den Schnitt zur Abfallseite –
    Außenkonturen wachsen, Löcher schrumpfen (Polygon-Versatz mit `shapely`, spitze Ecken).
  - *Haltestege* (`tab_count` 0–24 bzw. `tab_spacing_mm` = ein Steg je … mm Umfang,
    `tab_width_mm`): Lücken mit Laser aus, gleichmäßig verteilt und nicht in Ecken;
    Konturen unter 10 mm Umfang bekommen keine Stege.
  - *Anfahrt/Abfahrt* (`lead_in_mm`, `lead_in_arc`, `lead_out_mm`, 0–10 mm): auf der
    Abfallseite (außen bei Teilen, innen bei Löchern), 45°-Gerade oder tangentialer Viertelkreis;
    der Konturstart wird dafür von einer Ecke in die Kantenmitte verlegt. Passt die Anfahrt nicht
    (Arbeitsfläche, kleines Loch), wird sie gekürzt, senkrecht gesetzt oder weggelassen.
    Kreuzt eine An-/Abfahrt die eigene Kontur oder ein anderes Teil (alle Ebenen), wird ein
    anderer Startpunkt bzw. die Gegenrichtung versucht, dann gekürzt, erst zuletzt weggelassen;
    weggelassene Anfahrten meldet ein Hinweis nach Senden, Schätzung und Speichern.
  - *Überschnitt* (`overcut_mm`, 0–10 mm, wie LightBurns *Overcut*): die Kontur wird über den
    Startpunkt hinaus weiter geschnitten, damit kein Faden stehen bleibt; mit Haltestegen endet
    der Überschnitt 0,5 mm vor dem ersten Steg, eine Abfahrt beginnt an seinem Ende.
  - *Perforation* (`perf_cut_mm` Schnitt / `perf_skip_mm` Lücke, je 0–50 mm, wie LightBurns
    *Perforation Mode*): jede Linie der Ebene – auch offene Pfade, Steg-Stücke und Überschnitt –
    wird abwechselnd geschnitten und mit Laser aus übersprungen (Reiß- und Falzlinien in Karton,
    Abreißkanten). Kurze Schnitte (0,1–0,3 mm) ergeben eine Punktlinie (statt LightBurns
    *Dot Mode*, der Marlin-Dwell bräuchte). An-/Abfahrten und Füllungen bleiben durchgehend.
  Code: `src/lumacut_job/cutpath.py`; die Art jedes Teilpfads (`cut`, `lead_in`, `lead_out`,
  `tab`, `perf`) steht in `JobLayer.poly_kinds` (z. B. für eine Pfadvorschau).
- **Seriennummern** („Seriennummern…“, *Alt+N*, Toolbar „Auftrag“; Stapel-Fall von LightBurns
  „Variable Text“): ersetzt das ausgewählte Textobjekt durch ein Raster nummerierter Kopien.
  Vorlage mit Platzhaltern `{n}` (Nummer), `{n:3}` (mit Nullen, `007`), `{date}` (TT.MM.JJJJ),
  `{{`/`}}` für Klammern; Start, Schritt (auch negativ), Anzahl (≤ 500), Spalten, Abstand X/Y,
  Vorschau der ersten Werte. Höhe, Schrift, Drehung, Ebene und Streckung bleiben, die Breite folgt
  dem Text; die Kopien sind gruppiert, alles ist **ein** Rückgängig-Schritt. Passt das Raster
  nicht auf die Arbeitsfläche, wird nichts geändert. Option **„Beim Senden weiterzählen
  (variabler Text)“**: die Kopien behalten die Vorlage und bilden eine Serie variabler Texte –
  der erste Auftrag lasert Start … Start + (Anzahl − 1) × Schritt, jeder weitere macht dort
  weiter. Code: `src/lumacut_job/serial.py`.
- **Variabler Text** („Variabler Text…“, *Alt+V*, Menü „Auftrag“ und Design-Menü; wie LightBurns
  „Variable Text“ / „Merge CSV“): ausgewählte Textobjekte behalten auf der Arbeitsfläche und in
  der Projektdatei ihre **Vorlage**; erst beim Senden, Speichern als G-Code, Rahmen, in der
  Zeitschätzung und der Pfadvorschau werden die Platzhalter ausgewertet – gelasert wird der
  ausgewertete Text (Breite folgt dem Text, Höhe/Schrift/Drehung/Streckung bleiben, linke
  Kante fest). Platzhalter: `{n}` / `{n:3}` Zähler (Start, Schritt, Stellen, „Nächster Wert“,
  „Auf Start“), `{date}` / `{date:%Y-%m-%d}`, `{time}` / `{time:%H:%M:%S}` (Codes
  `%d %m %Y %y %H %M %S %j %V %%`), CSV-Spalten `{Name}` bzw. `{csv:Name}` / `{csv:2}`,
  `{row}` (Datenzeile), `{{`/`}}`. CSV-Serienbrief: Datei wählen (Trennzeichen `;` `,` Tab `|`
  automatisch, UTF-8 oder Windows-1252), Tabellenvorschau mit Klick auf die nächste Zeile,
  „Nach jedem Senden nächste Zeile“. Mehrere Kopien einer Serie bekommen fortlaufende Werte /
  Zeilen in Leserichtung (abschaltbar). Nach einem **erfolgreich hochgeladenen** Auftrag
  (Senden, Senden & Starten, Ein-Klick-Auftrag) werden Zähler und CSV-Zeile weitergeschaltet –
  ein Undo-Schritt, im Projekt gespeichert; ein abgelehnter oder fehlgeschlagener Upload, ein
  fehlgeschlagener Start oder das erneute Senden aus dem Auftragsverlauf schaltet nicht weiter.
  Fehler (unbekannte Spalte, CSV-Ende erreicht) verhindern das Senden mit einer Meldung.
  Doppelklick bearbeitet die Vorlage wie normalen Text. „Text in Pfade“ wandelt die Vorlage
  wörtlich um. Auf der Arbeitsfläche steht unter jedem variablen Text der **nächste Wert**
  („→ Nr. 042“, grün) – genau der Wert, den der nächste Auftrag lasert (Serie, Leserichtung,
  CSV-Zeile, „Nur Auswahl“); ein Fehler (fehlende CSV, unbekannte Spalte, CSV-Ende) erscheint
  rot als „⚠ …“. Datum/Uhrzeit werden alle 30 s aktualisiert. Ein-/ausschaltbar im Dialog
  („Nächste Werte auf der Arbeitsfläche anzeigen“, wird gespeichert); nur Anzeige, nie im
  Export. Code: `vartext_preview.py`. Code: `src/lumacut_job/vartext.py`, `vartext_qt.py`.
- **QR-Code** („QR-Code…“, *Alt+Q*, Toolbar/Menü „Auftrag“ und Design-Menü): Text oder Adresse
  (UTF-8) als QR-Code nach ISO/IEC 18004, Fehlerkorrektur L/M/Q/H, Version automatisch, Größe
  5–340 mm, Ruhezone (Standard 4 Module), „Invertiert“ für hell markierende Materialien. Die
  Module werden zu gefüllten Polygonen (gruppiert) und mit der Ebenen-Füllung graviert: Füllt die
  aktive Ebene nicht, legt der Dialog standardmäßig eine Ebene „QR-Code“ mit Schraffur 0,1 mm an.
  Ein Rückgängig-Schritt. Code: `src/lumacut_job/qr.py`, `qr_qt.py` (ohne Zusatzbibliothek).
  **Gemischte Segmente bei Text:** reiner ASCII-Text wird optimal in numerische,
  alphanumerische und Byte-Segmente aufgeteilt (dynamische Programmierung), aber nur, wenn das
  eine kleinere Version ergibt (z. B. „HTTPS://LUMACUT.EXAMPLE/P/4711“ M 3 → 2, Link mit langer
  Seriennummer M 4 → 3, 1000 Ziffern L 22 → 13) – sonst bleibt der Code Bit für Bit wie bisher
  (ein Byte-Segment). Der Dialog nennt die Segmente. Text mit Umlauten u. Ä. bleibt ein
  UTF-8-Byte-Segment. Gespeicherte Dateien öffnen unverändert (Module sind Polygone); erst
  „Code bearbeiten“ kodiert neu und kann dabei eine kleinere Version wählen.
  **Art** „GS1 QR-Code“: GS1-Elementstring „(01)09501101530003(17)261231(10)AB-12“ (feste Längen,
  Ziffern und Prüfziffern geprüft) mit dem Modusindikator *FNC1 an erster Stelle*, Trenner
  automatisch – GS1-Scanner lesen GTIN, Charge, MHD (Kennung `]Q3`). **Art** „GS1 Digital Link“
  (Sunrise 2027): derselbe Elementstring wird zur Web-Adresse
  `https://id.gs1.org/01/09501101530003/10/AB-12?17=261231` (genau ein Primärschlüssel – GTIN,
  SSCC, GLN … –, Schlüssel-Qualifier 22/10/21 im Pfad in Normreihenfolge, alle übrigen AIs als
  Abfrage, Sonderzeichen %-kodiert; eigene Domain wählbar) – oder eine fertige
  Digital-Link-Adresse wird geprüft und unverändert kodiert. Das Handy öffnet die Produktseite,
  Kassenscanner lesen die GTIN. Beide GS1-Arten nutzen gemischte Segmente (Ziffern numerisch,
  „%“/Großbuchstaben alphanumerisch, Rest Byte) und werden dadurch kleiner; „Beispiel“ setzt
  Musterdaten ein, die Zeile unter dem Inhalt zeigt die kodierten Daten. Code:
  `src/lumacut_job/gs1_link.py`.
- **Barcode** („Barcode einfügen…“, *Alt+C*, Menü „Auftrag“ und Design-Menü): Strichcode
  **Code 128** (ASCII, Zeichensatz A/B/C automatisch und kürzest möglich, Prüfsumme mod 103;
  Steuerzeichen für Scanner – Tab, Enter, GS … – über die Option „Steuerzeichen als \t \r \n \g
  \xHH eingeben“), **GS1-128** (Eingabe als Elementstring „(01)09501101530003(17)261231(10)AB-12“:
  feste Längen, Ziffern und Prüfziffern werden geprüft, FNC1 automatisch, Klartext mit Klammern),
  **EAN-13**, **EAN-8** und **UPC-A** (Prüfziffer wird ergänzt oder geprüft – falsche Prüfziffer
  → Fehlermeldung mit der richtigen). Modulbreite 0,1–5 mm (Hinweis unter 0,15 mm: Laserfleck),
  Höhe 2–300 mm, Ruhezone (Code 128: 10 Module je Seite, EAN/UPC nach Norm), optional Klartext
  darunter als Vektor-Umrisse (Schrift wählbar; EAN/UPC mit verlängerten Randzeichen),
  Strichkorrektur (Striche schmaler um den Laserfleck), **Invertiert** für Material, das beim
  Lasern hell wird (Hintergrund, Lücken, Ruhezone und Rand werden gelasert, Striche und Klartext
  bleiben stehen; Strichkorrektur macht dann die Striche breiter). Jeder Strich ist ein gefülltes Rechteck
  (benachbarte Module zusammengefasst), alles gruppiert; Füllung wie beim QR-Code (aktive Ebene
  oder neue Ebene „Barcode“ mit Schraffur 0,1 mm), ein Rückgängig-Schritt. Passt der Code nicht
  auf 360 × 340 mm, wird nichts eingefügt. Code: `src/lumacut_job/barcode.py`, `barcode_qt.py`
  (ohne Zusatzbibliothek).
- **Data Matrix** („Data Matrix…“, *Alt+X*, Menü „Auftrag“ und Design-Menü): 2D-Code nach
  ISO/IEC 16022 (ECC 200), alle quadratischen Größen 10 × 10 bis 144 × 144 und die sechs
  rechteckigen 8 × 18 bis 16 × 48 (für schmale Flächen; „Automatisch quadratisch“, „Automatisch
  rechteckig“ oder Mindestgröße wählbar), dazu die 18 **DMRE**-Rechtecke nach ISO/IEC 21471
  (8 × 48 bis 8 × 144, 12 × 64 bis 26 × 64 – flachere bzw. längere Codes für Kabel, Kanten und
  Etiketten; „Automatisch rechteckig inkl. DMRE“ oder feste Größe, bei zu wenig Platz zuerst
  die nächste DMRE-Größe gleicher Höhe). DMRE liest nicht jeder Scanner – der Dialog weist
  darauf hin; „Automatisch rechteckig“ bleibt bei ISO/IEC 16022. Die Kodierung wählt automatisch die kürzeste Mischung aus
  ASCII (Ziffernpaare), C40 (Großbuchstaben), Text (Kleinbuchstaben), X12 und Base 256 – lange
  Texte passen so in kleinere Symbole. Umlaute und Unicode als UTF-8 mit ECI 26 (Handy-Scanner
  lesen sie so zuverlässig), Reed-Solomon mit Block-Verschachtelung. Option **GS1-Daten**
  („(01)…(17)…(10)…“, Prüfung wie bei GS1-128) erzeugt GS1 DataMatrix mit FNC1. „Breite“ ist die
  Breite ohne Ruhezone (bei Rechtecken ergibt sich die Höhe), Ruhezone (Standard 2 Module),
  Invertiert und Ebenen-Logik wie beim QR-Code, ein Rückgängig-Schritt. Code: `src/lumacut_job/datamatrix.py`,
  `datamatrix_qt.py` (ohne Zusatzbibliothek).
- **Aztec-Code** („Aztec-Code…“, *Alt+Z*, Menü „Auftrag“ und Design-Menü): 2D-Code nach
  ISO/IEC 24778 mit Zielscheibe in der Mitte – braucht **keine Ruhezone** (Standard 1 Modul) und
  passt so gut auf kleine Teile und Etiketten. Alle Größen: kompakt 15 × 15 bis 27 × 27 (1–4
  Lagen) und voll 31 × 31 bis 151 × 151 (4–32 Lagen, mit Referenzgitter); „Automatisch“ oder
  Mindestgröße wählbar. Fehlerkorrektur einstellbar (10–90 %, Standard 23 % wie empfohlen). Die
  Kodierung wählt automatisch die kürzeste Mischung aus Groß-, Klein-, Misch-, Satzzeichen-, Ziffern-
  und Binärmodus; Umlaute und Unicode als UTF-8 mit ECI 26, Option **GS1-Daten** (FNC1, Prüfung wie
  bei GS1-128). „Kantenlänge“ ohne Ruhezone, Invertiert und Ebenen-Logik (neue Ebene „Aztec“ mit
  Schraffur 0,1 mm) wie beim QR-Code, ein Rückgängig-Schritt. Code: `src/lumacut_job/aztec.py`,
  `aztec_qt.py` (ohne Zusatzbibliothek).
- **PDF417-Code** („PDF417-Code…“, *Alt+F*, Menü „Auftrag“ und Design-Menü): gestapelter 2D-Code
  nach ISO/IEC 15438 (Ausweise, Versandetiketten, Bordkarten) – breit und flach, passt auf Leisten
  und Kanten. 1–30 Spalten („Automatisch“ wählt ein Seitenverhältnis von etwa 3 : 1) und 3–90 Zeilen,
  bis 928 Codewörter (z. B. 2692 Ziffern). Die Kodierung mischt automatisch Text- (Groß, Klein,
  Misch, Satzzeichen), Byte- und Ziffern-Kompaktierung; Umlaute und Unicode als UTF-8 mit ECI 26.
  Fehlerkorrektur Stufe 0–8 (Standard „Automatisch“ nach ISO-Empfehlung), Zeilenhöhe in Modulen
  (Standard 3, ISO-Minimum), Ruhezone (Standard 2 Module), Option **Kompakt** (ohne rechten
  Zeilenindikator, schmaler). „Breite“ ohne Ruhezone, Invertiert und Ebenen-Logik (neue Ebene
  „PDF417“ mit Schraffur 0,1 mm) wie beim QR-Code, ein Rückgängig-Schritt. Code:
  `src/lumacut_job/pdf417.py`, `pdf417_qt.py` (ohne Zusatzbibliothek).
- **Bogentext** („Bogentext…“, *Alt+B*): Text entlang eines Kreises als Vektor-Umrisse (ein
  Polygon je Buchstabe, gruppiert); oben/außen im Uhrzeigersinn oder unten/innen, Radius, Winkel,
  Bezugspunkt Mitte/Anfang/Ende, Zeichenabstand, Schrift/Fett/Kursiv. Ist genau ein Textobjekt
  ausgewählt, wird es übernommen und kann ersetzt werden. Code: `src/lumacut_job/arctext.py`,
  `arctext_qt.py`.
- **Code bearbeiten** („Code bearbeiten…“, *Alt+E*, oder Doppelklick auf einen Code): QR-Code,
  Barcode, Data Matrix, Aztec-, PDF417-Code und Bogentext bleiben nach dem Einfügen bearbeitbar. Der Dialog öffnet mit
  den gespeicherten Einstellungen (die Größe folgt einer seither geänderten Skalierung); „Übernehmen“
  erzeugt das Objekt neu – gleiche Mitte, Drehung, Ebene und Gruppen, ein Rückgängig-Schritt. Die
  Einstellungen werden in der Datei gespeichert und überstehen Kopieren/Einfügen und Anordnen;
  nach „Gruppierung aufheben“ oder einer Pfadoperation ist das Objekt wieder eine normale Fläche.
  Code: `src/lumacut_job/generated.py`, `generated_qt.py`.
- **Nur Auswahl** (Toolbar, umschaltbar): Senden, Schätzen, Rahmen und „G-Code speichern“
  verwenden nur die ausgewählten Objekte (Ebenen-Einstellungen bleiben); ohne Auswahl gibt es
  eine Fehlermeldung statt eines Auftrags. Die Pfadvorschau zeigt weiter das ganze Design.
- **Schätzung** (*Alt+P*): Zeit und Wege; bei mehreren Ebenen/Bildern zusätzlich die Zeit je Ebene.
- **G-Code speichern…** (*Alt+G*): optimierter G-Code des Designs als Datei (ohne
  Scan-Fokuskorrektur, die nur beim Senden über das Scan-Panel dazukommt).
- **Verlauf…** (*Strg+H*): die letzten 20 gesendeten Aufträge (alle Sendewege) mit Zeit und
  Schätzung; *Erneut senden* lädt den Auftrag wieder hoch (gestartet wird über „Start“),
  *Als Datei speichern*, *Entfernen*. Ablage: `%APPDATA%\LumaCut\LumaCut Studio\history`
  (`LUMACUT_HISTORY_DIR`).
- **Hilfe › Tastenkürzel** (*F1*): alle Kürzel des Fensters mit Suche.
- Die Arbeitsfläche zeigt 0–360 × 0–340 mm. Objekte werden still in der Fläche
  gehalten; der interne Safezone-Versatz wird nur beim Export für die Maschine
  addiert (`lumacut_canvas/workarea.py`).
- **Bekannte Grenzen:** Ungleichmäßiges Skalieren einer Mehrfachauswahl/Gruppe mit
  gedrehten Objekten skaliert diese ohne Scherung (Näherung; gleichmäßig mit
  *Umschalt* ist exakt). Gesperrte/ausgeblendete Gruppenmitglieder werden nicht mitbewegt.

### Material-Grundlage (Durchgänge aus Dicke und Tiefe je Durchgang)

`lumacut_canvas/material.py` (Qt-frei, Tests: `tests/test_material.py`). Feldnamen wie
`lumacut_materials.presets.Preset` (`thickness_mm`, `depth_per_pass_mm`); die
Materialbibliothek bleibt die Quelle für geplante Werte, dieses Modul ist die
schlanke Rechenbasis an der Ebene.

```python
from lumacut_canvas.material import (BUILTIN_MATERIALS, Material, plan_passes,
                                     layer_pass_plan, material_from_preset)
plan_passes(3.0, 0.8)            # passes 4, pass_depths (0.8, 0.8, 0.8, 0.6), total_mm 3.0
ed.apply_material(Material("Birke", 4.0, depth_per_pass_mm=1.0))   # 1 Undo-Schritt, passes = 4
ed.apply_material(m, target_depth_mm=1.5)   # Gravurtiefe statt Durchschnitt
layer_pass_plan(layer)           # mit den eingestellten layer.passes (Override), .reaches_target
```

- Tiefe = `target_depth_mm` oder (wenn 0) `thickness_mm`; `passes = ceil(Tiefe / depth_per_pass_mm)`,
  begrenzt auf 1–30. Abgeleitet, aber überschreibbar: von Hand gesetzte Durchgänge gelten.
- `BUILTIN_MATERIALS` sind **editierbare Startwerte, keine geprüften Empfehlungen** –
  immer erst einen Materialtest machen.
- **G-Code-Hook:** `document_to_gcode(doc, pass_hook=f)` ruft je Durchgang einer geplanten
  Ebene `f(job_layer, index, depth_mm, cumulative_mm)` und fügt die Zeilen nach
  `; PASS i OF n` ein (`gcode.depth_comment_hook` = nur Kommentare). Ohne Hook ist die
  Ausgabe unverändert; die Fokus-Absenkung bleibt `z_step`.
- **UI im Ebenen-Panel** („Material der Ebene“, Tests: `tests/test_material_panel.py`):
  Auswahl „— ohne Material —“, eingebaute Startwerte und – falls `lumacut_materials`
  eigene Presets gespeichert hat – „… (Preset)“ (nur gelesen; `LayersPanel(..., presets=f)`
  liefert eine eigene Quelle, `reload_presets()` liest neu). Felder Dicke, Zieltiefe
  („= Dicke“ bei 0) und Tiefe/Durchgang („aus“ bei 0). Durchgänge folgen automatisch
  (Abzeichen **auto**); von Hand geändert zeigt es **manuell**, „Auto“ setzt zurück.
  Darunter der Tiefenplan je Durchgang, rot mit ⚠, wenn die Zieltiefe nicht erreicht
  wird. Jede Änderung ist ein Undo-Schritt (`SetLayerAttrsCommand`). „manuell“ wird aus
  `passes ≠ ceil(Tiefe/Tiefe je Durchgang)` erkannt (kein eigenes Override-Feld).

### Füllung: Schraffur, Kreuzschraffur und Offset-Füllung je Ebene

Im Ebenen-Panel unter **Füllung der Ebene**: *Füllmodus* (Keine / Schraffur /
Kreuzschraffur / Offset-Füllung), *Linienabstand* in mm (0,05–20), *Winkel* in ° (0 = waagerecht,
gegen den Uhrzeigersinn; Kreuzschraffur fügt +90° hinzu, beim Einschalten
mit 0° wird 45° vorgeschlagen), *Kontur mitlasern* und *Bidirektional*
(abwechselnde Zeilenrichtung, kürzere Leerfahrten), *Überlauf* (nur Schraffur /
Kreuzschraffur), *Füllen* (welche Objekte gemeinsam gefüllt werden) und – nur bei
Offset-Füllung – *Von innen nach außen*. Jede Änderung ist ein Undo-Schritt.

- Gefüllt werden geschlossene Objekte: Rechteck, Ellipse, Polygon, Text
  (auch gedreht und gruppiert). Löcher (Buchstaben, Ringe) bleiben frei
  (Gerade-Ungerade-Regel); Linien/Freihand bleiben reine Konturen.
- **Offset-Füllung** (wie LightBurn „Offset Fill“): statt paralleler Linien
  konzentrische Konturen nach innen – erste Kontur einen halben Linienabstand
  innerhalb der Kante, danach je ein Linienabstand tiefer, bis die Fläche
  verschwindet; Löcher bekommen eigene Ringe nach außen. Jeder Ring wird ohne
  Absetzen gelasert (nur ein G0 je Ring), von außen nach innen mit kurzen
  Leerfahrten – bei Text, Logos und runden Formen oft schneller und sauberer
  als eine Schraffur mit vielen kurzen Zeilen. *Winkel* und *Bidirektional*
  sind dann ausgegraut. Stellen schmaler als ein Linienabstand bleiben ohne
  Ring (dort lasert die Kontur, wenn *Kontur mitlasern* an ist); mehr als
  5000 Ringe werden abgelehnt. Getrennte Inseln (z. B. die Buchstaben eines
  Texts) werden nacheinander ganz gefüllt, die nächstgelegene zuerst – der Kopf
  pendelt nicht für jede Tiefe zwischen den Buchstaben. *Von innen nach außen*
  dreht die Ring-Reihenfolge je Insel um (Kante zuletzt); die gewählte
  Reihenfolge wird im G-Code nie umgekehrt.
- **Füllen** (wie LightBurn „Fill shapes individually / Fill groups together /
  Fill all shapes at once“), gilt für Schraffur, Kreuzschraffur und
  Offset-Füllung: *Jedes Objekt einzeln* (Standard, wie bisher), *Gruppen
  zusammen* (alle Objekte einer obersten Gruppe als eine Fläche, ungruppierte
  einzeln) oder *Alle Objekte zusammen* (die ganze Ebene als eine Fläche).
  Gemeinsam gefüllte Objekte folgen der Gerade-Ungerade-Regel: ein Kreis in
  einem Rechteck wird zum Loch, auch wenn es zwei getrennte Objekte sind, und
  überlappende Teile bleiben frei. „Alle zusammen“ schraffiert eine Textzeile
  oder mehrere Objekte in einem Zug statt Objekt für Objekt.
- **Überlauf** (wie LightBurn „Overscanning“, 0–20 mm, Standard *Aus*): jede
  Schraffurlinie wird an beiden Enden mit ausgeschaltetem Laser verlängert
  (`G0` zum vorgezogenen Start, `G1 … S0` Anlauf, `G1 … S<p>` Linie, `G1 … S0`
  Auslauf) – der Kopf hat beim Einschalten schon volle Geschwindigkeit, die
  Ränder verbrennen nicht stärker. Am Rand der Arbeitsfläche wird der Überlauf
  gekürzt; Zeitschätzung und Pfadvorschau zeigen ihn als Leerfahrt. Offset-Füllung
  braucht keinen (Ringe ohne Absetzen), das Feld ist dort ausgegraut.
- **Scan-Versatz** („Scan-Versatz…“, Menü „Auftrag“; wie LightBurn „Scanning Offset
  Adjustment“): bei schneller, bidirektionaler Gravur brennt der Laser in Fahrtrichtung
  etwas zu spät, hin- und rücklaufende Linien liegen versetzt und senkrechte Kanten werden
  unscharf. Tabelle *Geschwindigkeit (mm/min) → Versatz (mm)* (bis 32 Zeilen, −2…2 mm),
  dazwischen linear interpoliert, außerhalb gilt der nächste Eintrag. Beim Senden, Speichern,
  Schätzen und in der Pfadvorschau wird jede Schraffur-/Kreuzschraffurlinie und jede
  Bild-Rasterzeile um den **halben** Versatz entgegen ihrer Fahrtrichtung verschoben (bei
  der Geschwindigkeit der Ebene bzw. des Bildes) – die Gravur bleibt mittig zur Kontur.
  Konturen und Offset-Füllung bleiben unverändert; am Rand der Arbeitsfläche wird die
  Verschiebung gekürzt. Die Tabelle gilt für die Maschine (App-Einstellung, nicht in der
  Datei); aus = G-Code Byte für Byte wie vorher. Der Planer-Hinweis nennt den aktiven
  Versatz. **Testmuster…**: Kalibrier-Auftrag mit einer Reihe Felder je Geschwindigkeit und
  steigendem Versatz je Spalte (beschriftet); „Senden (ohne Start)“ oder „Speichern…“ – je
  Reihe das Feld mit den geradesten Kanten in die Tabelle übernehmen.
  Die **Füllvorschau** auf der Arbeitsfläche zeigt bei aktivem Versatz die verschobenen
  Linien genau wie im G-Code (Blockreihenfolge und Startecke des Planers, Durchgang 1); der
  Plan wird zwischengespeichert, solange sich der Auftrag nicht ändert. Die Planung läuft im
  Hintergrund: die Arbeitsfläche bleibt bedienbar, bis dahin sind die unverschobenen Linien zu
  sehen; eine weitere Änderung bricht eine laufende Planung ab (bei ~1500 schraffierten
  Objekten ≈ 1,5 s im Hintergrund statt eingefrorener Oberfläche). Ohne aktive Tabelle bleibt
  die Vorschau wie bisher.
- G-Code: je Durchgang zuerst die Füllung (G0 an den Zeilenanfang, G1 mit
  Leistung/Geschwindigkeit der Ebene), danach die Kontur; Durchgangs-Hook
  (Tiefe je Durchgang) gilt auch für reine Füll-Ebenen. Ohne Füllung ist der
  G-Code unverändert.
- Reihenfolge: Beim Senden (Planer, „Leerfahrten reduzieren“) werden die
  Füllblöcke einer Ebene (je Objekt, Gruppe oder Ebene) nach dem nächsten
  Nachbarn sortiert statt in Objekt-Reihenfolge – Offset-Blöcke nur vorwärts
  (Ring-Reihenfolge bleibt); die Konturen beginnen dort, wo die Füllung endet.
  **Freie Startecke:** Schraffur- und Kreuzschraffurblöcke können an jeder ihrer vier
  Ecken beginnen – vorwärts, ganz rückwärts, Zeilen von der anderen Seite oder jede
  Zeile umgedreht. Bidirektional bleibt dabei das Hin-und-Her erhalten, unidirektional
  läuft jede Zeile weiter in dieselbe Richtung; Überlauf und Scan-Versatz folgen der
  gewählten Fahrtrichtung. Bei Gleichstand gewinnt die alte Wahl (Start oder Ende), ein
  einzelner Block bleibt Byte für Byte gleich. Danach verbessert ein 2-opt-/Or-opt-Durchlauf
  die Reihenfolge (Abschnitte umdrehen, 1–3 Blöcke verschieben; nur ganze Blöcke,
  Einstieg wie im G-Code an der nächsten Ecke) – bei bis zu einigen hundert Blöcken oft 5–20 %
  weniger Leerfahrt als nur „nächster Nachbar“, nie mehr. Deterministisch und mit
  festem Rechenbudget (≈ 0,5 s bei 1500 Blöcken, über 2000 Blöcke bleibt die
  Nachbar-Reihenfolge).
- Auf der Arbeitsfläche erscheint die Schraffur als dünne Linien in der
  Ebenenfarbe (Overlay `fill_preview`, nicht anklickbar). `export_svg` /
  `export_png` zeichnen sie mit `show_fill=True`.
- Datei: neue Felder (`fill_mode`, `line_interval_mm`, `hatch_angle`,
  `hatch_bidirectional`, `hatch_outline`, `fill_grouping`, `offset_inside_out`,
  `fill_overscan_mm`) werden nur geschrieben, wenn sie vom
  Standard abweichen; alte Dateien laden unverändert.
- Grenzen: Füllgruppen gelten nur innerhalb einer Ebene; Schnittfuge (Kerf) wirkt nur auf Konturen; mehr als
  20 000 Linien je Richtung werden abgelehnt (Linienabstand vergrößern).

### Pfadvorschau (Laserbahn, Reihenfolge, Zeit)

Knopf „Pfadvorschau“ in der oberen Leiste (Strg+Umschalt+P) zeichnet die
Laserbahn über die Objekte – erzeugt mit **demselben Generator wie das
Senden** (`lumacut_job.planner.optimized_document_gcode`: Planer-Reihenfolge,
Schraffur/Kreuzschraffur, Bild-Gravuren) und aus dem G-Code zurückgelesen
(`lumacut_canvas/toolpath.py`). Die Vorschau ändert weder Dokument noch
G-Code.

- Schnitte in der Ebenenfarbe, Leerfahrten grau gestrichelt
  (Zeilenwechsel innerhalb von Rastergravuren werden nicht gezeichnet).
- Jeder Lauf hat einen Startpunkt mit Reihenfolgenummer und einen Pfeil für
  die Richtung (Nummern ausgedünnt, wenn sie sich überdecken).
- Leiste: Schnitt- und Leerfahrtlänge, Zeit (`lumacut_job.estimate`), Zahl der
  Läufe; Ebenenfilter; Schieberegler zum Abspielen (erste *n* Bewegungen,
  Spitze markiert, Teillängen in der Anzeige).
- Neu gerechnet wird erst 250 ms nach der letzten Änderung und nur, solange
  die Vorschau an ist.

Bekannt: Die Startposition vor der ersten Fahrt ist unbekannt (der Pi
referenziert/parkt selbst), die erste Positionierfahrt zählt wie in der
Zeitschätzung mit 0 mm. Sehr große Rasterjobs werden vollständig gelesen;
bei vielen tausend Zeilen kann das Neuberechnen spürbar dauern.

### Anordnen: Ausrichten, Verteilen, Arrays

Knopf „Anordnen“ in der Aktionsleiste (und Untermenü im Kontextmenü), Rechnen in
`lumacut_canvas/arrange.py` (Qt-frei), Oberfläche in `arrange_ui.py`. Jede Aktion ist ein
Undo-Schritt; Gruppen zählen als eine Einheit und bleiben in sich unverändert.

- **Ausrichten** links / mittig / rechts / oben / mittig / unten (Strg+Umschalt+←/H/→/↑/V/↓):
  mehrere Einheiten an der Auswahl-Hüllbox, ein einzelnes Objekt an der Arbeitsfläche.
- **Verteilen** waagerecht/senkrecht: gleiche Lücken, die äußeren Einheiten bleiben
  stehen (ab drei Einheiten).
- **Raster-Array …**: Spalten × Zeilen, Lücke X/Y in mm (Schritt = Auswahlgröße + Lücke).
- **Kreis-Array …**: Anzahl inkl. Original, Mitte X/Y, Winkel (360° = geschlossen, sonst
  Bogen mit Anfang und Ende), „Kopien mitdrehen“ an/aus.
- Kopien bekommen neue IDs und eigene Gruppen; läge eine Kopie außerhalb der
  Arbeitsfläche oder wären es mehr als 500, passiert nichts (Meldung in der Statuszeile).

### Knoten bearbeiten (Werkzeug „Knoten“, Taste N)

- Polygon, Pfad oder Freihandlinie antippen: Knoten erscheinen (eckig = Gerade,
  rund = Kurve); die Skalier-Griffe sind so lange ausgeblendet.
- Knoten ziehen verschiebt ihn (ein Undo-Schritt je Zug, Raster fängt);
  Pfeiltasten verschieben den gewählten Knoten um 1 mm (Umschalt: 10 mm).
- Doppelklick/Doppeltippen auf ein Segment fügt dort einen Knoten ein, auf einen
  Knoten löscht ihn; Entf löscht den gewählten Knoten.
- Kontextleiste und Kontextmenü (Rechtsklick/langes Drücken): „+ Knoten“,
  „− Knoten“, „Kurve ⇄ Gerade“ (Segment ab dem gewählten Knoten, Catmull-Rom
  durch die Nachbarknoten), „Schließen/Öffnen“ (öffnet hinter dem gewählten
  Knoten) und „In Pfad“ für Rechteck, Ellipse und Linie (auch per Doppelklick).
- Gedrehte Objekte behalten ihre Drehung; Kurven landen gespeichert in `curves`
  und gehen wie alles andere über `shape_path` in Schraffur, Export und G-Code.
  „In Pfad“ macht aus einer Ellipse 16–32 Kurvenknoten (Abweichung ≤ 0,02 mm).

### Pfad: Boole-Operationen, Verschweißen, Versatz, Text in Pfade

Knopf „Pfad“ in der Aktionsleiste (und Untermenü im Kontextmenü), Rechnen in
`lumacut_canvas/pathops.py` (shapely), Oberfläche in `pathops_ui.py`. Jede Aktion ist ein
Undo-Schritt. Objekte zählen als Fläche nach der Gerade-Ungerade-Regel (wie die Füllung),
Drehung, Ellipsen und Text werden berücksichtigt.

- **Vereinigen** (Strg+Alt+U), **Abziehen** (Strg+Alt+S: unterstes Objekt minus alle
  darüber), **Schnittmenge** (Strg+Alt+I), **Ausschluss**: nur geschlossene Formen;
  Ergebnis ist *ein* Polygon mit Löchern an der Stelle des untersten Objekts.
- **Verschweißen** (Strg+Alt+W): wie Vereinigen, aber jede zusammenhängende Fläche wird
  ein eigenes Objekt.
- **Versatz …** (Strg+Alt+O): Abstand in mm (+ außen, − innen), Ecken rund/spitz/abgeschrägt,
  optional Original ersetzen. Offene Linien bekommen eine geschlossene Kontur im Abstand.
- **Text in Pfade umwandeln** (Strg+Umschalt+O): Text wird ein Polygon mit allen
  Buchstaben-Ringen – Füllung und G-Code bleiben gleich, die Datei hängt nicht mehr von
  installierten Schriften ab.
- **Schrift** (PropertyBar, sobald nur Text ausgewählt ist): Schriftart, Größe in pt
  (Geviert; skaliert die Box gleichmäßig), **F**ett, *K*ursiv und „In Pfade“. Schriftart
  und Schnitt behalten die Höhe und passen die Breite an; die letzte Wahl gilt für neue
  Texte. Gespeichert als `"bold"`/`"italic"` (nur wenn gesetzt).
- Polygone können dafür mehrere Ringe haben (`"rings"` in der Datei, nur wenn vorhanden).

### Schnittstellen für andere Module (Scan & Probe)

Alle Koordinaten in Bildschirm-mm der Arbeitsfläche (0,0 links oben; Anzeige und Maschine
haben den Nullpunkt oben rechts, siehe „Koordinaten“ oben). Getestet in
`tests/test_integration_hooks.py`.

```python
from lumacut_canvas.overlays import ImageOverlay, PainterOverlay
from lumacut_canvas.integration import add_dock_panel, make_action
from lumacut_canvas.workarea import Rect

ed = window.canvas                                    # CanvasEditor
# Bilder/Höhenkarten UNTER den Objekten (nicht anklickbar, nicht im Export/G-Code)
ed.add_overlay("scan", ImageOverlay(qimage))          # ganze Fläche 360 × 340 mm
ed.add_overlay("hoehe", ImageOverlay(heat, Rect(0, 0, 180, 170), opacity=0.6), z=10)
ed.add_overlay("marken", PainterOverlay(lambda painter, work: ...), z=20)
ed.overlay("hoehe").visible = False; ed.refresh_overlays()
ed.remove_overlay("scan")
# Bereich (ROI) wählen: nächster Mauszug, auf die Fläche begrenzt, Esc bricht ab
ed.roiSelected.connect(lambda x, y, w, h: ...)        # mm
ed.roiCancelled.connect(...)
ed.request_roi()                                      # ed.roi / ed.clear_roi()
# Panels und Aktionen aus main.py
dock = add_dock_panel(window, panel, "Scan & Probe")  # QDockWidget, objectName "dock_scan___probe"
ed.add_toolbar_action(make_action(window, "Bereich scannen", ed.request_roi,
                                  shortcut="Ctrl+Shift+B"), name="scan_roi")
```

`set_backdrop(img)` bleibt als einfacher Vollflächen-Hintergrund erhalten; Overlays
werden darüber und unter Raster und Objekten gezeichnet. Ein Fehler in einem
Overlay wird geloggt und bricht das Zeichnen nicht ab.

## Maschinenanbindung (Pi-API)

Das Panel **Maschine** (rechte Spalte) spricht direkt mit dem Flask-Dienst des
Pi 400 (`pi400/marlin/web.py`). Code: `src/machine/`
(`client.py` HTTP-Client nur mit stdlib, `worker.py` Status-Poller und Befehle
in eigenen Threads, `panel.py` Oberfläche, `settings.py` Einstellungen).

**Verbinden**
- Adresse: Standard `http://lumacut.local:8080`; `lumacut.local` oder eine IP
  genügt, `http://` und Port `8080` werden ergänzt.
- Schlüssel: wird bei jeder Anfrage als Header `X-LumaCut-Key` gesendet,
  nie geloggt und im Feld verdeckt angezeigt. Alternativ Umgebungsvariable
  `LUMACUT_KEY` (hat Vorrang und wird nicht gespeichert).
- Adresse, Schlüssel und „Automatisch verbinden“ werden per `QSettings`
  gespeichert (Windows: `HKCU\Software\LumaCut\LumaCut Studio`, Schlüssel
  im Klartext – wer das nicht will, nutzt `LUMACUT_KEY`).

**Statusanzeige** (farbig): Verbindung (getrennt / verbinde / verbunden /
Fehler / Schlüssel abgelehnt), SKR-USB, X/Y/Z, Homed, Laser (aktiv / aus /
unbekannt), Besitzer, Fokus-Z, Auftrag mit Fortschritt (Zeile/Gesamt),
letzter Fehler. Der Status wird jede Sekunde im Hintergrund abgefragt, und
die Oberfläche blockiert nie. Ist der letzte gute Status älter als 3 s (der Pi
antwortet während Home/Park/Abtasten erst danach), zeigt das Badge „Status
N s alt“, und alle Knöpfe außer NOT-AUS sind gesperrt.

**Bedienung → API**

| Knopf | Anfrage |
| --- | --- |
| NOT-AUS (Panel, Toolbar, Taste *Pause*) | `POST /api/action op=estop`: eigener Thread, 3 s pro Versuch, bis zu 3 Versuche bei Netzfehlern (zusammen höchstens ≈ 4 s, kein System-Proxy), auch während Home/Probe und ohne Verbindung; Rückmeldung „bestätigt“ / „NICHT bestätigt“ unter dem Knopf |
| Notstopp quittieren | `op=estop_reset` (mit Rückfrage; danach neu referenzieren) |
| Home | `op=home` |
| Jog X±/Y±/Z± | `op=jog axis=X\|Y\|Z distance=±0.1\|1\|10` (nur gehomed) |
| Fokus (G30) | `op=probe` – Pi merkt sich die Oberfläche und fährt vor dem ersten Laserstrich selbst auf Fokushöhe |
| Park | `op=park`: Laser aus, Z-Rückzug, X0/Y0 (nur gehomed) |
| Senden | `POST /api/upload` (multipart `file`, .gcode/.gc/.nc, max. 32 MB) |
| Starten / Ein-Klick | `op=start name=…` / `op=autorun name=…` (mit Rückfrage) |
| Rahmen (Rechteck / Gummiband), *Strg+Umschalt+F* / *Alt+Umschalt+F* | `op=frame gcode=… mode=box\|hull`: Umriss mit Laser aus, ohne Upload; der gesendete Auftrag bleibt geladen (nur gehomed, nicht während eines Auftrags; mit Rückfrage) |
| Abbrechen | `op=abort` (Auftrag oder Rahmenfahrt) |

Fehler des Pi (`{"error": …}`) erscheinen im Panel unter „Letzte Meldung“.

Alle Aufrufe mit Payload, Antwortfeldern, Fehlercodes und Zeitlimits, dazu
Zustandsautomat, NOT-AUS-Verhalten und Einstellungen:
**[docs/MACHINE_API.md](docs/MACHINE_API.md)**.

**Hinweise / offene Punkte im Pi-Dienst**
- Der Pi prüft `X-LumaCut-Key` bewusst nicht (Weboberfläche ohne Anmeldung).
  Die App sendet ihn trotzdem und zeigt HTTP 401/403 als „Schlüssel
  abgelehnt“ an, falls der Pi ihn einmal prüft.
- `op=park` und `op=frame` sind jetzt in `pi400/marlin/web.py` enthalten.
  Ein älterer Pi-Dienst meldet „bietet noch kein Parken über die API“ bzw.
  „bietet noch keine Rahmenfahrt über die API“, bis er aktualisiert ist.
- `/api/status` blockiert auf einem aktuellen Pi nicht mehr hinter
  Home/Park/Abtasten/Rahmen, sondern liefert einen Snapshot mit `busy` und
  `stale_ms` (Badge „Pi fährt“). Ein älterer Pi antwortet erst nach der
  Fahrt; die App toleriert das („Status alt“).
- Fremdbelegung (z. B. LightBurn) sperrt alle Fahrknöpfe außer NOT-AUS.
  Schließen der App während einer Fahrt fragt nach; die Maschine wird
  dadurch nicht gestoppt.
- Pi-Stand, Update-Anleitung und offene Punkte:
  [docs/PI_STATUS_UND_OFFENE_PUNKTE.md](../../docs/PI_STATUS_UND_OFFENE_PUNKTE.md).

## Kamera-Scan und Höhenmesh

Kachel-Scan, Objekterkennung, Mehrbereichs-Proben, Höhenmeshes und
Fokuskorrektur: siehe [docs/SCAN_PROBE.md](../../docs/SCAN_PROBE.md) (`src/scanprobe/`).

## Materialbibliothek

*Mehr › Materialwerte bearbeiten › Materialbibliothek …* (Strg+Umschalt+M) – Editor;
gewählt wird oben unter „1 Material“. Startwerte (Leistung, mm/min, Durchgänge,
Fokus-Absenkung je Durchgang) für 25 Materialien und LaserTree LT-80W
(10 W optisch) bzw. 5/10/20/40-W-Dioden auf die aktive Ebene anwenden,
Presets speichern, 3D-Relief aus Graustufenbild. Warnliste für nicht
laserbare Materialien. Siehe [docs/MATERIALS.md](docs/MATERIALS.md)
(`src/lumacut_materials/`).

## Import (SVG, DXF, PDF, AI, EPS, xTool, Bilder)

*Datei › Importieren…* (Strg+I) oder Datei per Drag-and-drop auf die Arbeitsfläche ziehen.

- **SVG**: Pfade, Grundformen, Transformationen; Einheiten über `viewBox`/`width`/`height` in mm.
- **DXF** (über `ezdxf`, inkl. Blöcke/INSERT); Einheit aus `$INSUNITS`, ohne Angabe mm.
- **PDF** (über `pypdf`): Vektorpfade einer Seite (bei mehreren Seiten wird gefragt), in mm
  (1 pt = 25,4/72 mm), Seitendrehung berücksichtigt. Als dünne Ringe gespeicherte Linien
  (Qt, Word) werden zu einer Kontur zusammengefasst. Text nur, wenn in Pfade umgewandelt;
  eingebettete Bilder, Beschneidungspfade und verschlüsselte PDFs werden nicht übernommen.
- **AI** (Illustrator): normale AI-Dateien sind PDF-kompatibel → PDF-Import (Seitenwahl).
  Alte AI (≤ 8, reines PostScript) nur mit Ghostscript.
- **EPS**: über Ghostscript, falls installiert (PATH, `C:\Program Files\gs\…` oder
  `LUMACUT_GHOSTSCRIPT`); sonst klarer Hinweis „als SVG/PDF exportieren“. Nicht mitgeliefert.
- **xTool `.xcs` / `.xs`**: Pfade, Rechtecke (mit Eckenradius), Kreise/Ellipsen, Linien,
  Polygone, Text (als Glyphenkonturen, sonst Textobjekt) und Bitmaps der ersten Arbeitsfläche;
  Laserwerte werden nicht übernommen, unbekannte/ausgeblendete Objekte gezählt und übersprungen.
  Tabelle und Grenzen: [Anforderungen §9.2](../../docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md).
- **PNG/JPG/BMP**: wird als **Bildobjekt** eingefügt (Größe aus der DPI-Angabe, sonst 96 dpi).
  *Datei › Bildeinstellungen…* (Strg+Umschalt+I) öffnet den Dialog (Modus Schwellwert / Floyd-Steinberg /
  Atkinson / **Jarvis / Stucki / Sierra** / Bayer / **Halbton** (Rasterzellen je Zoll + Winkel) /
  **Zeitungsdruck** (45°-Rasterpunkte) / **Skizze** (nur Kanten, Zeichenstil) / Graustufen /
  3D-Tiefe, Linienabstand, Leistung max./min., Geschwindigkeit, Durchgänge, bidirektional, Negativ,
  **Punktbreitenkorrektur**). Die Gruppe **Bildanpassung** (wie LightBurn „Adjust Image“) ändert
  das Bild vor dem Modus: **Schwarzpunkt** / **Weißpunkt** (Tonwertkorrektur: Grauwerte bis zum
  Schwarzpunkt werden reines Schwarz, ab dem Weißpunkt reines Weiß, dazwischen linear gestreckt;
  0 / 255 = unverändert), **Helligkeit** und **Kontrast** (−100…100 %), **Gamma** (0.2…5, > 1
  hellt die Mitteltöne auf) und **Schärfen** (Unscharf maskieren, Stärke und Radius in
  Laserpunkten); *Zurücksetzen* stellt „unverändert“ wieder her, **Auto-Tonwert** setzt Helligkeit
  und Kontrast so, dass der Tonwertumfang des Bildes (ohne je 0,5 % Ausreißer) von Schwarz bis Weiß
  reicht (Gamma, Schärfen und Schwarz-/Weißpunkt bleiben). Die Anpassung gilt für alle Modi
  inkl. 3D-Tiefe und wird gespeichert; bei gedrehten Bildern bleiben die Ecken der Hüllbox
  ungelasert. Rechts zeigt
  eine **Live-Vorschau** das Bild so, wie es gelasert wird (ein Vorschaupunkt = ein Laserpunkt im
  eingestellten Linienabstand, große Bilder als Ausschnitt aus der Mitte, Anteil gelaserter
  Punkte) – samt **Drehung** des Objekts und mit genau den Pixeln des Auftrags; darunter ein
  **Histogramm** der Grauwerte (hell = Bild, dunkel = nach der Bildanpassung) mit dem Anteil
  reinen Schwarz / Weiß und dem Tonwertumfang, blaue Striche markieren Schwarz- und Weißpunkt;
  bei gedrehten Bildern zählt das Histogramm nur das gedrehte Bild (ohne die Ecken). Für Fotos auf dem Diodenlaser sind Jarvis oder Stucki meist die beste Wahl. Die
  Punktbreitenkorrektur (LightBurn „Dot Width Correction“) kürzt jede gelaserte Strecke um den
  eingestellten Wert (je Ende die Hälfte), damit der Strahl Punkte nicht verbreitert – Startwert
  etwa die halbe Strahlbreite, höchstens der Linienabstand; 0 = aus. Bilder werden im
  Auftrag vor den Vektor-Ebenen graviert.
- **Bild nachzeichnen** (*Datei › Bild nachzeichnen…*, *Alt+T*, wie LightBurn „Trace Image“):
  wandelt das ausgewählte Bild in Vektorkonturen. Schwellwert (dunkler = Kontur; Startwert aus den
  Bildeinstellungen), Invertieren, Glättung (Weichzeichnen vor dem Schwellwert), Toleranz
  (Vereinfachung in mm) und Mindestfläche (Flecken/kleine Löcher ignorieren), mit Live-Vorschau.
  Ergebnis: Polygone auf den Pixelkanten, Löcher als Ringe (Schraffur, Kerf und „innen zuerst“
  behandeln sie richtig), mehrere Teile gruppiert, deckungsgleich über dem Bild in der aktiven
  Ebene; **ein** Rückgängig-Schritt, auf Wunsch inkl. Löschen des Bildes. Sehr verrauschte Bilder
  werden mit Hinweis abgelehnt (Glättung/Mindestfläche erhöhen). Code:
  `src/lumacut_import/trace.py` (Qt-frei, OpenCV + shapely), Dialog `trace_qt.py`.
- Jeder Import ist **ein** Rückgängig-Schritt und wird in die Arbeitsfläche (360×340 mm) eingepasst.
- Code: `src/lumacut_import/` (Qt-frei) und `src/lumacut_import/qt.py` (Menü, Drop).

## Geführter Ablauf

Rechts oben zeigt das Panel **Ablauf** die Schritte
Home → Scan → Markieren → Probe → Fokus → Rahmen → Auftrag → Parken.
Jeder Schritt hat einen Status (Erledigt / Bereit / Gesperrt / Übersprungen / Läuft) und zeigt bei
„Gesperrt“ den Grund (nicht verbunden, nicht referenziert, Notstopp verriegelt, Maschine
beschäftigt, keine markierten Bereiche, kein Design …). *Ausführen* ruft die vorhandenen Aktionen
des Maschinen- bzw. Scan-Panels auf (alle Sicherheitsprüfungen bleiben dort und auf dem Pi),
*Überspringen* gilt für alle Schritte außer Home und Auftrag. Eine Änderung am Design öffnet Rahmen
und Auftrag wieder. Logik: `src/lumacut_workflow/steps.py` (Qt-frei), UI: `src/lumacut_workflow/qt.py`.

## Automatisches Sichern und Wiederherstellung

Solange das Projekt ungespeicherte Änderungen hat, sichert das Studio es alle 60 s atomar nach
`%APPDATA%\LumaCut\LumaCut Studio\autosave` (Ordner per `LUMACUT_AUTOSAVE_DIR` änderbar). Nach einem
Absturz bietet der nächste Start **„Projekt wiederherstellen?“** an; das wiederhergestellte Projekt
gilt als ungespeichert. Beim Speichern, beim Rückgängigmachen bis zum gespeicherten Stand und beim
normalen Beenden wird die Sicherung gelöscht. Mehrere gleichzeitig laufende Studios stören sich
nicht (Sperrdatei je Sitzung). Code: `src/lumacut_session/`.

**Air-Assist:** nicht umgesetzt – auf dieser Maschine sind M7 (Licht), M8 (Absaugung) und M9
(beides aus) bereits belegt; siehe `docs/REVIEW_GAP_ANALYSIS_2026-10-25.md` §8.

## Tests

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests
```

Die Maschinen-Tests (`tests/test_machine_*.py`) laufen gegen einen lokalen
Fake-Pi (`tests/fake_pi.py`) und brauchen keine Hardware.

Canvas-Tests (`tests/test_model.py`, `test_layers.py`, `test_serialization.py`,
`test_undo.py`, `test_editor.py`, `test_gcode.py`) laufen ebenfalls offscreen.
Unter Windows (PowerShell):

```powershell
pip install -r requirements.txt -r requirements-dev.txt
$env:QT_QPA_PLATFORM = "offscreen"; python -m pytest tests
```
