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
2. **Design** – Menü: Importieren …, Text, Rechteck, Ellipse, Polygon, Vieleck / Stern, Freihand, Linie
   (… Codes / Bogentext / Text auf Pfad …) und zuletzt das Werkzeug „Messen“.
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
Werkzeugleiste „Auftrag“ (Schnittoptionen mit Kerf, Haltestege, Anfahrt, Überschnitt, Rampe, Perforation;
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

- **Werkzeuge:** Auswahl (V), Rechteck (R), Ellipse (E), Linie (L), Polygon (P), Vieleck / Stern (S),
  Freihand (F), Text (T), Messen (M, siehe unten), Trimmen (Alt+Umschalt+X, siehe „Überstände abschneiden“),
  Passmarken (Alt+Umschalt+M, siehe „Anordnen“).
  *Umschalt* beim Zeichnen = Quadrat/Kreis/45°-Linie; Klick ohne Ziehen legt
  ein 20-mm-Objekt an. **Text direkt auf der Arbeitsfläche** (wie LightBurn / xTool): mit dem
  Text-Werkzeug klicken und lostippen, Doppelklick auf einen Text bearbeitet ihn an Ort und
  Stelle. Ein Eingabefeld erscheint direkt unter dem Text (ohne Platz darunter darüber), jede
  Eingabe zeigt sich sofort auf der Arbeitsfläche mit Schrift, Größe und Satz des Texts;
  Enter = neue Zeile, Strg+Enter / ✓ / Klick daneben = fertig, Esc / ✕ = abbrechen. Genau ein
  Undo-Schritt („Text einfügen“ / „Text ändern“), keiner ohne Änderung; ✓ / ✕ im Touch-Modus
  44 px (die Bildschirmtastatur öffnet sich mit dem Feld). Polygon: Klick = Punkt,
  Doppelklick/Enter oder Klick auf den ersten Punkt = schließen, Rücktaste = Punkt weg.
  Freihand: ziehen zeichnet einen offenen Pfad (ohne Raster); beim Loslassen wird er mit
  Ramer-Douglas-Peucker vereinfacht (Toleranz 0,2 mm, `tools.FREEHAND_TOLERANCE_MM`), Esc bricht ab.
- **Eckenradius** (Rechtecke, wie LightBurn *Shape Properties › Corner Radius* / xTool
  „Eckenradius“): Feld „Ecken“ in der Eigenschaftsleiste, sobald nur Rechtecke ausgewählt
  sind – positiv = abgerundete Ecken, negativ = nach innen gewölbte Ecken (Viertelkreis um
  die Ecke), 0 = scharf; ein Undo-Schritt für die ganze Auswahl. Der Radius bleibt beim
  Skalieren in mm gleich und wird auf die halbe kürzere Seite begrenzt (Statuszeile meldet
  es); das Rechteck bleibt ein Rechteck (Box = Umrissbox). Anzeige und SVG-Export mit echten
  Bögen, G-Code / Füllung / Kerf / Stege / Boole / Versatz über `shape_polygons`
  (Sehnenfehler ≤ 0,02 mm, nur G1); manuelle Stege rutschen beim Ändern auf den Bogen,
  „Knoten“ / „Kombinieren“ übernehmen die Bögen als Punkte. Datei: `"radius"` (mm), nur wenn
  gesetzt. xTool-Rechtecke mit Eckenradius werden als solche Rechtecke importiert.
- **Vieleck / Stern** (Werkzeug S, wie LightBurns *Polygon*-Werkzeug / xTool „Polygon“ und
  „Stern“): vom Mittelpunkt aus ziehen – der Abstand ist der Außenradius, die erste Spitze zeigt
  nach oben, *Umschalt* dreht sie in 15°-Schritten zur Maus; Tippen legt 20 mm Durchmesser an.
  Felder in der Eigenschaftsleiste (sichtbar mit dem Werkzeug oder wenn nur Vielecke / Sterne
  ausgewählt sind): „Seiten“ (3–100, Standard 6), „Stern“ und „Innen“ (Innenradius 5–95 % des
  Außenradius); eine Änderung ist ein Undo-Schritt für die Auswahl und zugleich die Vorgabe für
  das nächste Objekt; Mittelpunkt, Größe und Drehung bleiben. Das Objekt ist ein gewöhnliches
  Polygon (G-Code / Füllung / Kerf / Stege / Boole / Knoten wie jedes Polygon, nur G1) mit
  `"regular": {"sides", "inner"}` in der Datei; nach „Knoten“, „Vereinfachen“ oder Boole ist es
  ein normales Polygon (Felder verschwinden), Verschieben / Skalieren / Drehen behalten es.
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
- **Pfade aufräumen** (Menü „Pfad“, wie LightBurn *Auto-Join*, *Close Selected Paths With
  Tolerance*, *Delete Duplicates*, *Optimize Selected Shapes*): „Pfade verbinden“ (Alt+J) fügt offene Pfade/Linien einer
  Ebene mit Endpunkten ≤ 0,05 mm Abstand zu Ketten zusammen – lose DXF-Strecken werden
  geschlossene Polygone, ineinander liegende Ketten *ein* Polygon mit Löchern (Schraffur lässt
  das Loch frei, Kerf / Stege / An-/Abfahrt und „innen zuerst“ greifen). „Pfade schließen
  (Toleranz) …“ (Alt+Umschalt+J) schließt einzelne Pfade mit Endlücke ≤ 0,01–20 mm (Enden in der
  Mitte zusammenführen oder Verbindungslinie, Zähler live, Kurvensegmente bleiben). „Duplikate
  löschen“ (Alt+Umschalt+D; Alt+D öffnet „Datei“) entfernt deckungsgleiche Objekte derselben
  Ebene (0,01 mm, egal welcher Startpunkt / welche Richtung) – sonst würden sie doppelt gelasert.
  „Offene Formen auswählen“ markiert alle offenen Pfade/Linien. Ohne Auswahl gilt alles
  Bearbeitbare; erzeugte Objekte (Codes) und Bilder bleiben unberührt; je **ein**
  Rückgängig-Schritt. Nach einem Import nennt die Statusleiste offene und verbindbare Konturen;
  *Datei › Import-Einstellungen …* erledigt Verbinden / Löcher kombinieren / Duplikate löschen auf
  Wunsch gleich beim Import (siehe „Import“).
  Liegen offene Pfade/Linien auf einer Ebene mit Füllung, warnt der Hinweis beim Senden,
  „Senden und starten“, Schätzen und Speichern („Achtung: N offene Konturen auf Füll-Ebene …
  wird nur als Linie geschnitten, nicht gefüllt (M verbindbar) – Pfad › „Pfade verbinden“
  (Alt+J) oder „Pfade schließen“ (Alt+Umschalt+J)“), wie LightBurns Warnung beim Start.
  „Pfade vereinfachen …“ (Alt+O, wie LightBurn *Optimize Selected Shapes*) entfernt Knoten,
  die höchstens die eingestellte Abweichung (Standard 0,05 mm, 0,005–5 mm) von der Kontur
  abweichen (Douglas-Peucker) – importierte Kurven, Nachzeichnungen und Freihandstriche mit
  Tausenden Mini-Strecken werden zu wenigen `G1`-Zügen; der Dialog zeigt live „Knoten: vorher →
  nachher (−N %)“. Geschlossene Formen bleiben geschlossen, offene behalten ihre Enden, Ebene,
  Gruppen, Drehung und Stapelplatz bleiben, kleine Löcher gehen nie verloren. Pfade mit
  Kurvensegmenten bleiben unverändert, außer mit „Kurven in Linien umwandeln“ (keine Bögen –
  der Pi lehnt G2/G3 ab).
  „Überstände abschneiden …“ (Alt+Umschalt+O, wie LightBurns *Trim Shapes*, ohne Klickwerkzeug und
  damit per Finger bedienbar) entfernt die kleinen Überstände, die Linien an Kreuzungen haben
  (Raster, Rahmen, CAD-Import): das freie Ende eines offenen Pfads hinter einer Kreuzung mit einem
  anderen offenen Pfad oder der Kontur einer markierten geschlossenen Form, höchstens „Überstand
  höchstens“ lang (Standard 3 mm, 0,1–50 mm; der Dialog zeigt live Anzahl und Länge). Es fällt nur
  weg, was kürzer ist als der Rest des Pfads – gleich lange Kreuzarme, Ecken und T-Stöße bleiben.
  Danach lassen sich die Ecken mit „Pfade verbinden“ (Alt+J) zu geschlossenen Konturen verbinden.
  Ebene, Gruppen, Priorität und Laufrichtung bleiben, ein Undo-Schritt; Formen ohne Überstand
  bleiben unverändert.
  Werkzeug **„Trimmen“** (Alt+Umschalt+X, Werkzeugleiste und Pfad-Menü, wie LightBurns *Trim Shapes*
  per Klick): Tippen auf eine Linie, einen offenen Pfad oder den Umriss eines Rechtecks / einer
  Ellipse / eines Polygons entfernt das Stück bis zu den zwei nächsten Kreuzungen mit anderen Formen
  (oder bis zum freien Ende) – auch innere Stücke zwischen zwei Kreuzungen, längere Überstände und
  doppelt übereinanderliegende Strecken. Mit der Maus zeigt es vorher rot gestrichelt, was wegfällt;
  mit dem Finger trimmt der Tipp direkt (Strg+Z holt es zurück). Geschlossene Formen werden dabei zum
  offenen Pfad, Löcher eines Polygons bleiben geschlossen; Ebene, Gruppen, Priorität und
  Laufrichtung bleiben, ein Undo-Schritt je Tippen. Es schneidet an allen sichtbaren Formen (auch
  gesperrten, Text, QR-Codes), getrimmt werden nur Linien und Umrisse entsperrter Ebenen.
  **Ziehen über mehrere Stücke** (Maus oder Finger, wie LightBurns Trimmen mit gedrückter Taste)
  zieht eine graue Zuglinie; jedes Stück, das sie kreuzt, wird rot gestrichelt gezeigt und fällt
  beim Loslassen weg – z. B. alle inneren Stege eines Rasters mit einem Strich, auch mehrere Stücke
  derselben Form. Die Stücke gelten gegen den Stand vor dem Zug (genau die Vorschau), alle zusammen
  sind ein Undo-Schritt „Trimmen“; ein zweiter Finger (Zoomen) bricht den Zug ab.
  Auch **Selbstkreuzungen** teilen eine Form in Stücke: bei einer Acht (z. B. aus einem Import) fällt
  per Tippen eine Schlaufe weg und die andere bleibt eine geschlossene Kontur (füllbar, mit Kerf und
  Stegen), bei einem Pfad mit Schleife lässt sich die Schleife oder das Ende hinter der eigenen
  Kreuzung entfernen. **Manuelle Stege und der Startpunkt** bleiben auf allen Konturen, die
  geschlossen bleiben (Außenring beim Trimmen eines Lochs, übrige Schlaufe einer Acht); die auf
  einem entfernten oder nun offenen Stück entfallen, die Statuszeile nennt ihre Zahl.
  Code: `lumacut_canvas/pathjoin.py` (Qt-frei bis auf Kurven), `pathsimplify.py`, `pathtrim.py`, `pathjoin_ui.py`,
  `trim_ui.py`.
- **Ecken abrunden …** (Pfad-Menü, Alt+Umschalt+R, wie LightBurns *Radius*-Werkzeug / xTool
  „Eckenradius“ für Polygone und Sterne): „Abrunden“ ersetzt jede Ecke durch einen Bogen mit dem
  eingestellten Radius (abgeflacht auf ≤ 0,02 mm, nur `G1`), „Abschrägen“ durch eine gerade Fase.
  „Alle Ecken“, „Nur Außenecken (Spitzen)“ – z. B. die Zacken eines Sterns – oder „Nur
  Innenecken“; „Knick ab“ (Standard 10°) lässt flache Knicke abgeflachter Kreise unverändert. Ist
  eine Kante zu kurz, wird der Radius dort kleiner (der Dialog zählt es live). Gilt für Polygone,
  Vielecke / Sterne (werden gewöhnliche Polygone), Pfade (Enden bleiben) und alle Löcher; Rechtecke
  bekommen beim Abrunden ihren Eckenradius (Feld „Ecken“ bleibt editierbar). Auswahl, sonst alles
  Bearbeitbare; Drehung, Ebene, Gruppen, Stapelplatz und manuelle Stege bleiben; ein
  Rückgängig-Schritt. Code: `lumacut_canvas/pathfillet.py` (Qt-frei), `pathfillet_ui.py`.
- **Gruppen:** Strg+G gruppiert, Strg+Umschalt+G löst eine Ebene der Gruppierung
  (verschachtelte Gruppen möglich). Ein Klick wählt immer die ganze Gruppe;
  Verschieben, Skalieren, Drehen, Löschen und Duplizieren wirken auf die Gruppe.
  Gruppenmitglieder bleiben auf ihren Ebenen (Laserparameter je Ebene).
- **Ansicht:** Mausrad = Zoom (ohne Auswahl um den Cursor, mit Auswahl auf die
  Auswahlmitte zu – sie bleibt stehen bzw. wird zentriert; 0,4–60 px/mm), mittlere Maustaste oder Leertaste+Ziehen = Verschieben,
  Strg+0 = Fläche einpassen, Raster und Fangen (1 mm) umschaltbar, Lineale in mm,
  Cursorposition in mm in der Statusleiste.
- **An Objekten fangen** (Alt+Umschalt+S, Schalter neben „Am Raster fangen“, Vorgabe an –
  wie LightBurns *Snap to Objects* und xTools Ausrichtungslinien): beim Zeichnen (Rechteck,
  Ellipse, Linie, Polygon, Vieleck / Stern, Text), beim Ziehen eines Skalier-Griffs und beim
  Verschieben von Knoten rastet der Punkt auf Knoten, Ecken, Kantenmitten, Mittelpunkte,
  Ellipsen-Quadranten und Linien-Enden anderer Objekte (und Ecken / Mitte der Arbeitsfläche)
  ein, sonst je Achse auf deren Box-Kanten und -Mitten; beim Verschieben der Auswahl rasten
  ihre Kanten / Mitte an den Kanten und Mitten anderer Objekte ein. Fangabstand 7 px
  (Touch-Modus 14 px), unabhängig vom Zoom; der Objektfang hat Vorrang vor dem 1-mm-Raster.
  Magentafarbene Hilfslinien und eine Marke zeigen das Ziel, die Statusleiste die Art
  („Fang: Kantenmitte“). Alt beim Ziehen setzt ihn aus; ausgeblendete Ebenen fangen nicht,
  gesperrte schon. Die Wahl wird in QSettings (`canvas/object_snap`) gespeichert. Code:
  `lumacut_canvas/objsnap.py` (Qt-frei), `objsnap_ui.py`.
- **Messen** (Werkzeug M, Knopf nach „Startpunkt“ in der Werkzeugleiste und im Menü „Design“ – wie
  LightBurns *Measure*-Werkzeug): von Punkt zu Punkt ziehen oder zwei Punkte antippen (nach dem
  ersten Tipp folgt das Ende der Maus). Beide Punkte fangen wie die Zeichenwerkzeuge an Knoten,
  Ecken, Kantenmitten, Mittelpunkten, Quadranten und Linien-Enden („An Objekten fangen“, 7 px /
  Touch-Modus 14 px), sonst am 1-mm-Raster; Alt setzt den Objektfang aus, Umschalt rastet die
  Richtung in 15°-Schritten ein. Auf der Zeichenfläche erscheinen Strecke, Endmarken und ein
  Schild mit Abstand, ΔX / ΔY (angezeigte Koordinaten, Nullpunkt oben rechts – X zählt nach
  links) und Winkel (0° = nach rechts, gegen den Uhrzeigersinn positiv), in der Anzeige-Einheit
  mm / Zoll; die Statusleiste zeigt dasselbe. Die Messung bleibt stehen, bis neu gemessen, Esc
  gedrückt oder das Werkzeug gewechselt wird; Strg+C (im Werkzeug) oder „Messung kopieren“ im
  Kontextmenü kopiert den Abstand („42.43 mm“ – passt in jedes Längenfeld). Eine Messung ist
  kein Objekt: kein Undo-Schritt, wird nicht gespeichert, ändert keinen G-Code. Code:
  `lumacut_canvas/measure.py` (Qt-frei), `measure_ui.py`.
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
  optional `z_step` (Fokus-Absenkung je Durchgang) und `z_offset` (relativer
  Fokus-Versatz der ganzen Ebene, negativ = näher am Material; Materialtest-
  Fokusachse), optional Material/Dicke/Tiefe je Durchgang (siehe „Material-Grundlage“).
  Die **Geschwindigkeits-Einheit** (Auswahl neben dem Feld: *mm/min* oder *mm/s*, wie
  LightBurn) gilt für Ebenen-Liste, Ebenen-Feld, Bild-Einstellungen, Materialtest und
  Scan-Versatz zugleich und wird als App-Einstellung gemerkt; intern und in Datei/G-Code
  bleibt es mm/min (gleicher G-Code in beiden Ansichten, Eingaben in mm/s werden auf
  0,001 mm/min genau umgerechnet).
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
  Auf der Zeichenfläche ist der sichtbare Teil der Park-Ecke als **rot schraffierte
  Sperrzone** „Park-Ecke“ eingezeichnet (Kopf v6: Streifen 48 × 5 mm oben rechts; folgt
  `park_corner_mm` des Pi), unter den Objekten, nicht anklickbar und nicht im Export. Bei
  Ursprung „Aktuelle Position“ / „Benutzer-Ursprung“ zeigt sie die Stelle **relativ zum
  Design**, die am Kopf / Benutzer-Ursprung mit dem gewählten Bezugspunkt in der Ecke landen
  würde (Beschriftung „Park-Ecke (am Ursprung …)“; ohne bekannte Kopfposition / gespeicherten
  Ursprung ausgeblendet). **Live-Warnung:** Schon beim Verschieben, Einfügen oder Einblenden
  einer Ebene prüft Studio nach derselben Regel wie der Pi (umschließendes Rechteck des
  Auftrags – sichtbare Ebenen, mit „Nur Auswahl“ nur die Auswahl), ob der Auftrag abgelehnt
  würde: die Zone wird kräftiger rot, nennt die Zahl der Objekte darin (bzw. „Motiv-Umriss
  reicht hinein“, wenn nur das Gesamtrechteck die Ecke berührt) und die Statusleiste meldet es
  einmal – „Park-Ecke wieder frei.“, sobald es behoben ist. Die Live-Prüfung nutzt die
  Objektboxen (etwas vorsichtiger als der G-Code-Laser-an-Bereich beim Senden, z. B. bei Text
  oder weißen Bildrändern). **Schnitt-Optionen** brennen außerhalb der Objektboxen:
  Kerf-Versatz nach außen, An-/Abfahrten und der Scan-Versatz der Schraffur. Könnten sie das
  Ergebnis ändern (Objektboxen frei, Boxen + größtmögliche Reichweite in der Ecke), plant
  Studio den Auftrag genau wie beim Senden und prüft dessen Laser-an-Bereich – die Warnung
  „An-/Abfahrt / Versatz reicht hinein!“ stimmt dann mit der Ablehnung beim Senden überein;
  weit weg von der Ecke wird nicht geplant. Der Überlauf der Schraffur läuft mit Laser aus und
  zählt (wie am Pi) nicht. Code: `src/lumacut_job/park_zone.py`.
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
    Konturen unter 10 mm Umfang bekommen keine Stege. Wie LightBurn außerdem:
    *Höchstens Stege je Kontur* (`tab_max`, nur mit Steg-Abstand, „unbegrenzt“ = 0 – lange
    Konturen bekommen sonst sehr viele Stege), *Innere Formen ohne Stege* (`tab_skip_inner`,
    *Skip Inner Shapes*: Konturen, die ganz in einer anderen Kontur derselben Ebene liegen –
    Löcher, Buchstaben-Innenformen, Teile in einem Rahmen – bleiben ohne Stege) und
    *Steg-Leistung* (`tab_cut_power`, 0–95 %, *Tab Cut Power*): statt einer Lücke wird der Steg
    mit kurzen Pulsen quer angeschnitten (≈ alle 0,4 mm ein Puls mit der Leistung der Ebene,
    Länge = Prozent der Periode, dazwischen `G1 … S0` – der Kopf fährt ohne Halt weiter);
    höher = schwächerer Steg, leichter auszubrechen. Der Dialog nennt Pulszahl und -länge.
  - *Manuelle Stege* (Werkzeug „Stege“, Alt+Umschalt+T, wie LightBurns *Tab tool*): Tippen auf
    den Umriss einer geschlossenen Form setzt dort einen Steg, Tippen auf einen Steg entfernt
    ihn, Ziehen schiebt ihn entlang des Umrisses; Pfad › „Manuelle Stege entfernen“ löscht die
    Stege der Auswahl. Die Stege gehören zum Objekt (`Shape.tabs`, im Projekt gespeichert) und
    folgen Verschieben / Skalieren / Drehen / Duplizieren, Knoten bearbeiten, Vereinfachen,
    Zerlegen / Kombinieren und „Text in Pfade“. Beim Senden bekommt eine Kontur mit eigenen
    Stegen genau diese (Stegbreite und Steg-Leistung der Ebene, auch ohne Anzahl / Abstand und
    mit „Innere Formen ohne Stege“) statt der automatischen; Stegbreite 0 schaltet alle Stege
    der Ebene ab. Die Arbeitsfläche markiert jeden Steg als orangen Balken in Stegbreite.
    Pfad › „Stege gleichmäßig setzen …“ (Alt+Umschalt+G, wie LightBurns *Auto-place tabs*)
    verteilt manuelle Stege auf einmal auf die Auswahl (ohne Auswahl auf alle bearbeitbaren
    Objekte): „Anzahl je Kontur“ oder „Abstand“ (ein Steg je … mm Umfang, „Höchstens“),
    „Mindestumfang“, „Ecken meiden“ (wie die automatischen Stege von Ecken und Konturstart
    weggeschoben), „Innere Konturen auslassen“ (Löcher – auch eigene Objekte derselben Ebene)
    und „Vorhandene manuelle Stege ersetzen“; Zähler live im Dialog, ein Undo-Schritt, danach
    lässt sich jeder Steg einzeln verschieben oder entfernen.
    Code: `lumacut_canvas/tabs.py`, `tabs_ui.py`, `lumacut_job/cutpath.py`.
  - *Startpunkt* (Werkzeug „Startpunkt“, Alt+Umschalt+A, wie LightBurns *Set Start Point*):
    Tippen auf den Umriss einer geschlossenen Form legt dort fest, wo ihre Kontur beginnt
    (ein vorhandener Startpunkt der Form wird ersetzt), Tippen auf den Startpunkt entfernt ihn,
    Ziehen schiebt ihn entlang des Umrisses; Pfad › „Startpunkte entfernen“ löscht die
    Startpunkte der Auswahl. Ein Startpunkt je Objekt (`Shape.start`, im Projekt gespeichert),
    er folgt Verschieben / Skalieren / Drehen / Duplizieren, Knoten bearbeiten, Vereinfachen,
    Ecken abrunden, Zerlegen / Kombinieren und „Text in Pfade“. Beim Senden beginnt die Kontur
    genau dort – auch mit „Besten Startpunkt wählen“ / „Möglichst an Ecken beginnen“ und mit
    Kerf (der Punkt wird auf die versetzte Kontur gelegt); die Reihenfolge plant der Planer
    weiter. Anfahrt, Überschnitt, Abfahrt, Stege und Perforation setzen am Startpunkt an (eine
    blockierte Anfahrt darf nur die Laufrichtung wechseln oder kürzer werden, der Start wird
    nicht verlegt). Die Arbeitsfläche markiert jeden Startpunkt als grünen Punkt mit einem
    Pfeil in Laufrichtung. Ohne Startpunkt ändert sich nichts.
    Code: `lumacut_canvas/startpoint.py`, `startpoint_ui.py`, `lumacut_job/planner.py`.
  - *Richtung umkehren* (Pfad › „Richtung umkehren“, Alt+Umschalt+U, wie LightBurns
    *Edit › Reverse Shape Direction*): kehrt die Laufrichtung der gewählten Objekte um (ein
    Undo-Schritt, zweimal = wie gezeichnet; alle Vektorobjekte inkl. Linien und offener Pfade,
    `Shape.reverse`, im Projekt gespeichert). Im Werkzeug „Startpunkt“ kehrt Umschalt+Tippen
    auf einen Startpunkt die Richtung um, Umschalt+Tippen auf den Umriss setzt dort den
    Startpunkt und kehrt die Richtung um (wie LightBurns Umschalt-Klick), bei offenen Pfaden /
    Linien nur die Richtung. Geschlossene Konturen laufen beim Senden in der Gegenrichtung ab
    demselben Startpunkt (auch mit Kerf, Anfahrt, Überschnitt, Stegen), offene Pfade beginnen
    am anderen Ende – der Planer behält diese Richtung auch mit „Beste Richtung wählen“.
    Umgekehrte Objekte ohne Startpunkt zeigen einen hohlen grünen Kreis mit Pfeil in
    Laufrichtung. Bleibt erhalten bei Knoten bearbeiten, Vereinfachen, Ecken abrunden,
    Schließen, Zerlegen, „Text in Pfade“ und Kombinieren (nur wenn alle Teile umgekehrt
    waren). Ohne Umkehr ändert sich nichts.
    Code: `lumacut_canvas/direction.py`, `startpoint_ui.py`, `export.py`, `lumacut_job/planner.py`.
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
  - *Rampe* (`ramp_mm`, 0–20 mm, „aus“ = 0; `ramp_start_power` 0–95 %; `ramp_outer_only`; wie
    LightBurns *Ramp Length* / *Ramp Outer Only*): die Leistung steigt am Anfang jeder
    Schnittlinie (Kontur samt Überschnitt, offener Pfad) in Stufen von ≈ 0,5 mm (höchstens 20)
    von der Startleistung auf die Ebenen-Leistung und fällt am Ende ebenso ab – kein
    Einbrandloch am Start-/Endpunkt; mit Überschnitt überlappen sich Anfang und Ende voll.
    An-/Abfahrt, Steg-Pulse und Füllungen bleiben bei voller Leistung, perforierte Ebenen ohne
    Rampe; „Rampe nur an Außenkonturen“ schneidet Löcher mit voller Leistung. Die Stufen sind
    eigene `G1 … S…` ohne zusätzliches `G0` (kein `G2`/`G3`).
  - *Perforation* (`perf_cut_mm` Schnitt / `perf_skip_mm` Lücke, je 0–50 mm, wie LightBurns
    *Perforation Mode*): jede Linie der Ebene – auch offene Pfade, Steg-Stücke und Überschnitt –
    wird abwechselnd geschnitten und mit Laser aus übersprungen (Reiß- und Falzlinien in Karton,
    Abreißkanten). Kurze Schnitte (0,1–0,3 mm) ergeben eine Punktlinie (statt LightBurns
    *Dot Mode*, der Marlin-Dwell bräuchte). An-/Abfahrten und Füllungen bleiben durchgehend.
  - *Überlappende Linien entfernen* (`overlap_tol_mm`, 0–1 mm Toleranz, „aus“ = 0, z. B.
    0,05 mm; wie LightBurns *Remove overlapping lines*): Linien, die in derselben Ebene schon
    geschnitten wurden – die gemeinsame Kante zweier aneinander stoßender Teile, teilweise
    übereinander liegende Strecken, doppelte Kreise mit anderem Startpunkt –, werden nur einmal
    gelasert (nahezu parallel ≤ ~11°, Abstand ≤ Toleranz; Kreuzungen und Berührungen bleiben).
    Die später geschnittene Linie verliert den Abschnitt, „innen zuerst“ bleibt; eine
    geschlossene Kontur wird dabei zu einem offenen Linienzug. Wirkt nur auf Konturen/Linien,
    nie auf Füllungen und Bilder, nicht über Ebenen hinweg und **nicht** auf Ebenen mit Kerf,
    Haltestegen, An-/Abfahrt oder Überschnitt (die brauchen die ganze Kontur – der Dialog und
    der Hinweis nach dem Senden sagen das); Perforation gilt danach für die Reststücke. Der
    Hinweis nach Senden / Schätzung / Speichern nennt die eingesparte Länge. Code:
    `src/lumacut_job/overlap.py`.
  Code: `src/lumacut_job/cutpath.py`; die Art jedes Teilpfads (`cut`, `lead_in`, `lead_out`,
  `tab`, `perf`, bei Steg-Leistung `tab_pulse` / `tab_off`) steht in `JobLayer.poly_kinds`
  (z. B. für eine Pfadvorschau).
- **Optimierungseinstellungen** („Optimierung…“, *Alt+Umschalt+K*, Toolbar „Auftrag“; wie
  LightBurns *Optimization Settings*, gilt für das ganze Projekt, ein Undo-Schritt, in der
  Projektdatei als `cut_order` – nur gespeichert, wenn vom Standard abweichend): *Optimierung und
  Umsortierung aktiv* (aus = Konturen und Füllblöcke in Zeichenreihenfolge, mit gezeichnetem
  Startpunkt und gezeichneter Richtung), *Innere Formen zuerst*, *Leerfahrten verkürzen*
  (nächste Kontur zuerst), *Besten Startpunkt wählen*, *Möglichst an Ecken beginnen*
  (*Choose corners*: Start geschlossener Konturen an der nächsten Ecke mit ≥ 40° Knick, die
  Einstichstelle fällt dort kaum auf; Kreise beginnen am nächsten Punkt), *Beste Richtung
  wählen* (offene Pfade vom näheren Ende) und *In Richtung schneiden* (*Cut in direction
  order*: von oben nach unten / unten nach oben / links nach rechts / rechts nach links, Zeile
  für Zeile – eine Zeile = Konturen, deren Vorderkante innerhalb der halben Höhe der vordersten
  liegt; in der Zeile die nächste). Die Ebenen laufen von unten nach oben. *Reihenfolge*
  (wie LightBurns *Order by Layer* / *Order by Group* / *Order by Priority*): **Nach Ebenen** (Standard – erst alle
  Objekte der untersten Ebene, dann die nächste) oder **Nach Gruppen** – jede oberste Gruppe
  (Strg+G) wird mit allen ihren Ebenen fertig graviert und geschnitten, bevor die nächste
  beginnt (z. B. ein Namensschild nach dem anderen: verrutscht ein ausgeschnittenes Teil,
  ist die Gravur der anderen schon fertig bzw. noch unberührt); Objekte ohne Gruppe laufen
  zusammen zum Schluss (z. B. der Plattenrand). Die Gruppen folgen den Einstellungen oben
  (aus = Zeichenreihenfolge; „Innere Formen zuerst“: eine Gruppe, die ganz in einer anderen
  liegt, zuerst; „In Richtung schneiden“ zeilenweise; sonst die nächste Gruppe ab dem
  Maschinen-Nullpunkt), innerhalb einer Gruppe planen die Ebenen wie gewohnt. Im G-Code steht
  vor jeder Gruppe ein Kommentar `; GROUP i OF n`; ohne Gruppen bleibt der Auftrag gleich.
  **Nach Priorität** (wie LightBurns *Order by Priority*): jedes Objekt hat eine
  Schnitt-Priorität (Feld **„Priorität“** in der Eigenschaftsleiste, 0–999, erscheint bei
  Auswahl, sobald „Nach Priorität“ gewählt ist oder ein Objekt schon eine Priorität hat; ein
  Rückgängig-Schritt für die ganze Auswahl). Zuerst laufen alle Objekte der kleinsten
  Priorität mit allen ihren Ebenen, dann die nächste – unabhängig von Ebenen- und
  Gruppenreihenfolge (z. B. Ausrichtmarken / ein Teststück zuerst, eine Ebene „Schneiden“
  vor einer Gravur, die erst auf dem fertigen Teil kommen soll). Bilder werden weiter vorab
  graviert. Im G-Code steht vor jeder Priorität `; PRIORITY p (i OF n)`; haben alle Objekte
  dieselbe Priorität, bleibt der Auftrag gleich. Die Statusmeldung nennt die Prioritäten und
  warnt, wenn eine innere Form (Loch, Gravur) eine höhere Priorität als ihre Außenform hat
  und darum erst nach dem Ausschneiden käme. Zerlegen, Kombinieren (kleinste Priorität),
  Boole, Versatz, Text in Pfade, Vereinfachen und Schließen behalten die Priorität
  (`Shape.priority`, `export.priority_units`, `src/lumacut_canvas/priority_ui.py`).
  Senden, Pfadvorschau, Zeitschätzung, Rahmen und „G-Code speichern“ planen gleich
  (`JobLayer.cut_order`, `export.cut_units`). Code: `src/lumacut_job/planner.py`, Dialog
  `src/lumacut_job/optimize_qt.py`.
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
  `{row}` (Datenzeile), **Tastatureingabe** `{input:Name}` / `{eingabe:Name}` (optional
  `{input:Name=Vorgabe}`; wie EzCads Tastatur-Text: beim Senden, Senden & Starten,
  Ein-Klick-Auftrag und „G-Code speichern“ fragt „Eingaben für den Auftrag“ jede Bezeichnung
  einmal ab, vorbelegt mit dem zuletzt eingetippten Wert bzw. der Vorgabe; Abbrechen sendet
  nicht; der Wert gilt nur für die Sitzung – Arbeitsflächen-Hinweis, Rahmen, Pfadvorschau und
  Zeitschätzung nehmen den zuletzt eingetippten, davor die Vorgabe oder „‹Name›“),
  `{{`/`}}`. CSV-Serienbrief: Datei wählen (Trennzeichen `;` `,` Tab `|`
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
  (ein Byte-Segment). Der Dialog nennt die Segmente. **Umlaute / Sonderzeichen:** mit
  „UTF-8 kennzeichnen (ECI)“ (Standard für neue Codes) bekommt Text mit Nicht-ASCII-Zeichen
  („Größe“, „25 °C“, „€“, Emoji …) die Zeichensatz-Kennung ECI 26 (UTF-8) – Handys und Scanner
  müssen den Zeichensatz nicht raten, und Ziffernfolgen dürfen dann auch numerische Segmente
  werden. Japanischer Text (Kana / Kanji, alles in Shift JIS) nutzt den Kanji-Modus (13 statt
  24 Bit je Zeichen, z. B. 52 Kanji M 9 → 5). Reiner ASCII-Text ändert sich nicht; ältere Codes
  ohne die Einstellung öffnen beim Bearbeiten mit ausgeschaltetem Häkchen und bleiben
  bitgleich (ein UTF-8-Byte-Segment ohne Kennung, der Dialog weist darauf hin). Gespeicherte
  Dateien öffnen unverändert (Module sind Polygone); erst „Code bearbeiten“ kodiert neu und kann
  dabei eine kleinere Version wählen.
  **Art** „GS1 QR-Code“: GS1-Elementstring „(01)09501101530003(17)261231(10)AB-12“ (feste Längen,
  Ziffern und Prüfziffern geprüft) mit dem Modusindikator *FNC1 an erster Stelle*, Trenner
  automatisch – GS1-Scanner lesen GTIN, Charge, MHD (Kennung `]Q3`). **Art** „GS1 Digital Link“
  (Sunrise 2027): derselbe Elementstring wird zur Web-Adresse
  `https://id.gs1.org/01/09501101530003/10/AB-12?17=261231` (genau ein Primärschlüssel – GTIN,
  SSCC, GLN … –, Schlüssel-Qualifier 22/10/21 im Pfad in Normreihenfolge, alle übrigen AIs als
  Abfrage, Sonderzeichen %-kodiert; eigene Domain wählbar) – oder eine fertige
  Digital-Link-Adresse wird geprüft und unverändert kodiert. **Kurzname-Aliases** aus Digital Link URI Syntax 1.1 (`/gtin/`, `/sscc/`, `/gln/`, `/lot/`, `/ser/`, `?exp=` …) werden beim Einfügen immer akzeptiert (Groß-/Kleinschreibung egal); die Checkbox „Kurzname (/gtin/, /lot/, …)“ (Standard aus) schreibt die Aliase statt numerischer AIs (`…/gtin/…/lot/…?exp=…`). Ohne Häkchen bleiben die Adressen bitgleich zu älteren Dateien. Das Handy öffnet die Produktseite,
  Kassenscanner lesen die GTIN. Beide GS1-Arten nutzen gemischte Segmente (Ziffern numerisch,
  „%“/Großbuchstaben alphanumerisch, Rest Byte) und werden dadurch kleiner; „Beispiel“ setzt
  Musterdaten ein, die Zeile unter dem Inhalt zeigt die kodierten Daten. Code:
  `src/lumacut_job/gs1_link.py`.
  **Art** „Micro QR (klein, M1–M4)“: ISO/IEC 18004 Micro QR – ein Finder, 11×11 bis
  17×17 Module, für Bauteilkennzeichnung und beengte Flächen. Version automatisch
  (kleinste passende), Fehlerkorrektur D (nur M1, Erkennung) / L / M / Q (Q nur M4);
  Modi numerisch, alphanumerisch und Byte (UTF-8); kein ECI, kein Kanji (UTF-8-Bytes
  für Umlaute). Ruhezone Standard **2** Module (Norm), Größe = Kantenlänge ohne
  Ruhezone, „Invertiert“ und Ebenen-Logik wie beim vollen QR (neue Ebene „Micro-QR“
  mit Schraffur 0,1 mm). „Code bearbeiten…“ öffnet denselben Dialog mit Art Micro QR.
  Reiner Python-Encoder ohne Zusatzbibliothek (`src/lumacut_job/micro_qr.py`); der
  bisherige QR-Pfad bleibt unverändert.
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
  ausgewählt, wird es übernommen und kann ersetzt werden. „Schriftart“ wählt
  „Umrissschrift“ oder eine **Einlinien-Schrift** („Einlinie (Sans)“ / „Einlinie
  (Schreibschrift)“, wie LightBurns Single-Line-Fonts auf dem Kreis): dann ist jeder Buchstabe
  ein offener Pfad mit einem Teilpfad je Strich, einmal als Linie gelasert und nie gefüllt
  (ideal für Ringbeschriftungen auf Untersetzern, Skalen und Stempeln); Fett ist dann aus,
  fehlende Zeichen nennt die Info („?“). Ein ausgewählter Einlinien-Text bringt seine Schrift
  mit, neue Bogentexte übernehmen die zuletzt für Texte gewählte Einlinien-Schrift; „Bogentext
  bearbeiten“ behält sie. Code: `src/lumacut_job/arctext.py`, `arctext_qt.py`.
- **Text auf Pfad** („Text auf Pfad…“, *Alt+Umschalt+P*, wie LightBurns *Text on Path*):
  Text an eine ausgewählte Linie, einen (offenen) Pfad, ein Polygon / einen Stern, ein Rechteck
  oder eine Ellipse hängen – ein Polygon je Buchstabe, gruppiert, wie „Text in Pfade“ unabhängig
  von installierten Schriften und für Füllen / Schneiden / Kerf / Stege nutzbar. Jeder Buchstabe
  wird starr gesetzt und nach der Sehne seines Vorschubs auf dem Pfad gedreht (Knicke und enge
  Kurven bleiben ruhig; „Buchstaben mit dem Pfad drehen“ aus = alle aufrecht). Einstellungen:
  „Lage“ in % der Pfadlänge (geschlossene Umrisse beginnen oben in der Mitte und laufen im
  Uhrzeigersinn: 0 % = oben, 50 % = unten; offene am Anfang der Linie), „Bezugspunkt“
  Mitte / Anfang / Ende, „Seite“ (Oberseite oder andere Seite gegen die Pfadrichtung – z. B.
  unten auf einem Kreis von links nach rechts lesbar), „Abstand vom Pfad“ (± mm, −Höhe/2 =
  mittig auf dem Pfad), Zeichenabstand, Schrift / Fett / Kursiv; Info mit Text- und Pfadlänge
  (auf offenen Pfaden wird über das Ende hinaus verlängert und gemeldet). Ein mit ausgewählter
  Text wird übernommen und kann ersetzt werden, der Pfad optional gelöscht (nur Hilfslinie);
  ein Rückgängig-Schritt. Mit „Schriftart“ = Einlinie wird jeder Buchstabe ein offener Pfad
  (Striche, nie gefüllt) – wie beim Bogentext. Code: `src/lumacut_job/pathtext.py`, `pathtext_qt.py`, Pfad-Kurve in
  `lumacut_canvas/alongpath.py`.
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
  Die Zeit enthält wie beim Pi-Ablauf die Anfahrt aus der Park-Ecke (Z von 1 auf 20 mm, erste
  Fahrt ab X0/Y0) und das Parken danach (ggf. Z hoch, Eilgang nach X0/Y0, Z runter) –
  „· Anfahrt/Parken 8 s“ in Schätzung, Start-Rückfrage, Sendemeldung, Verlauf und Pfadvorschau;
  Referenzfahrt und Abtasten des automatischen Ablaufs zählen nicht mit. Mit verbundenem Pi
  gelten dessen Fahrhöhe (Z-Rückzug bzw. Materialstärke + 20 mm, `travel_z_mm`) und Parkhöhe
  (`config.park_z_mm`, zuletzt gesehene Werte auch offline); die Anfahrt beginnt an der
  Kopfposition, und bei „Aktuelle Position“ / „Benutzer-Ursprung“ wird der Auftrag wie vom Pi
  versetzt geplant („Zeit schätzen“ nennt Höhen und Versatz).
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

### Materialtest: Parameter je Achse (Leistung, Tempo, Linienabstand, Durchgänge, Fokus)

*Auftrag › Materialtest…* legt ein Testraster an (`lumacut_job/material_test.py`, Tests:
`tests/test_material_test.py`, `tests/test_material_test_params.py`,
`tests/test_layer_z_offset.py`). Wie LightBurns *Material Test* (X-/Y-Parameter),
*Interval Test* und *Focus Test* ist der Parameter je Achse wählbar:
„Spalten-Parameter“ / „Zeilen-Parameter“ = Leistung, Geschwindigkeit, Linienabstand,
Durchgänge oder Fokus-Versatz (Standard: Spalten Leistung, Zeilen Geschwindigkeit – das
bisherige Raster, G-Code byte-gleich).

- Parameter auf einer Achse laufen von „… von“ bis „… bis“; die übrigen gelten fest
  (Feld ohne „von“, „bis“ gesperrt) – z. B. Linienabstand 0,05–0,25 mm × Leistung bei
  fester Geschwindigkeit.
- Linienabstand-Test nur mit „Füllen (Gravur)“ oder „Bild“; gleicher Parameter auf beiden
  Achsen oder Linienabstand mit „Kontur“ sperren OK mit Hinweis.
- **Fokus-Versatz** (LightBurn *Focus Test*): relativ zum Fokus beim Start des Auftrags
  in mm (Standard −1…+1, Bereich ±`MAX_FOCUS_DROP_MM`); negativ = näher am Material
  (Kopf senken). Setzt `Layer.z_offset` der Zelle; der G-Code senkt/hebt relativ
  (`G91`/`G0 Z…`/`G90`) zu Beginn der Ebene und stellt nach der Ebene (nach einer
  etwaigen `z_step`-Rückfahrt) wieder her – braucht motorisierte Z (LumaCut hat sie).
  Mit Füllen, Kontur und Bild-Zellen; `Fokus von`/`bis` erscheinen nur, wenn Fokus auf
  einer Achse liegt.
- Jede Zelle bleibt eine eigene Ebene `Test P<Leistung>% F<mm/min>` (von der
  Materialbibliothek als Testzelle erkannt; Durchgänge stehen in der Ebene, der getestete
  Linienabstand in `line_interval_mm` der Ebene – Füllung bleibt aus, die Zelle ist eine
  Serpentine im Abstand der Zelle; der Fokus-Versatz steht in `z_offset`, nicht im Namen).
- Beschriftung: Leistung %, Geschwindigkeit mm/s, Linienabstand mm, Durchgänge „3x“,
  Fokus mit Vorzeichen („−1“, „+0.5“); breite Zeilen-Beschriftungen verbreitern die
  Beschriftungsspalte (Arbeitsflächen-Prüfung inklusive).
- Ein Undo-Schritt; Pi-sicherer G-Code wie jede andere Ebene.
- **Bild-Testzellen** (wie LightBurns *Interval Test* „Dithered Image“, für Fotogravur):
  „Art“ = „Bild (Graustufen-Verlauf)“ legt in jede Zelle dasselbe Testbild als
  Bildobjekt. **Bildquelle**: Verlauf (Weiß links → Schwarz rechts, Standard,
  byte-gleich zu früheren Rastern), Stufenkeil (16 gleiche Graustufen-Bänder) oder
  Eigenes Bild… (PNG/JPG/BMP → 8-Bit-Graustufen, in alle Zellen eingebettet).
  Graviert im gewählten „Bildmodus“ (Schwellwert, Floyd-Steinberg, Atkinson,
  Jarvis, Stucki, Sierra, Bayer, Halbton, Zeitungsdruck, Graustufen, 3D-Tiefe;
  Skizze nicht) mit Leistung (bei Schwarz), Geschwindigkeit, Linienabstand und
  Durchgängen der Zelle; „Min.-Leistung (Weiß)“ gilt für alle Zellen (höchstens
  die kleinste Leistung). Alle Achsen-Parameter gehen, auch der Linienabstand-Test.
  Die Bilder laufen vor der Beschriftung (Bilder vor Vektoren), die Zellen-Ebenen
  heißen wie bisher (Preset aus Testzelle funktioniert); maßgeblich für den G-Code
  sind die Bild-Einstellungen der Zelle (*Datei › Bildeinstellungen…*), nicht die
  Ebenenwerte. **Modus-Parameter** (wie die Bild-Einstellungen in LightBurns
  Interval Test): je nach Bildmodus erscheinen Schwellwert (Schwellwert),
  Halbton-Zellen und Rasterwinkel (Halbton), 3D-Stufen und Z-Schritt je Stufe
  (3D-Tiefe, Fokus-Absenkung höchstens 3 mm) sowie für alle Modi Helligkeit,
  Kontrast, Gamma und Negativ; sie gelten für alle Bild-Zellen. Unveränderte Werte
  = Vorgaben, G-Code byte-gleich zu früheren Rastern.
  Tests: `tests/test_material_test_image.py`, `tests/test_material_test_image_options.py`.
- **Bildoptionen als Achse** („… (Bild)“ im Spalten-/Zeilen-Parameter, nur mit Art „Bild“):
  Zahlenwerte von/bis (Schwellwert, Halbton, Helligkeit, Kontrast, Gamma, Schärfen,
  Scan-Winkel, Winkel-Schritt, Schwarz-/Weißpunkt, Punktbreite, Overscan und – im Modus
  3D-Tiefe – 3D-Stufen und Z-Schritt; die Fokus-Absenkung Z-Schritt × (Stufen − 1) wird je
  Zelle geprüft), Negativ / Bidirektional als aus / an über genau 2 Spalten / Zeilen und
  die **Gradationskurve**: in der Liste „Kurven“ die zu testenden Vorlagen anhaken (je eine
  Spalte / Zeile, Reihenfolge per Ziehen, mindestens 2, höchstens 12; eine eigene Kurve eines
  geöffneten Rasters erscheint als „Benutzerdefiniert“). **Kurve zeichnen…** öffnet den
  Kurven-Editor der Bildeinstellungen über dem Histogramm des Testbilds (Vorlage: eine
  Kurvenvorlage, die Kurve eines Bildes im Dokument oder die gewählte Kurve) und hakt die
  gezeichnete Kurve an; *Bearbeiten…* (Doppelklick) ändert eine eigene Kurve an Ort und Stelle
  (eine Vorlage bleibt, das Ergebnis kommt als eigene Kurve dazu), *Entfernen* nimmt eigene
  Kurven heraus. Die Kurven der Bilder im Dokument (ausgewählte zuerst) stehen als „Bild N“ in
  der Liste und in „Kurve“ der weiteren Bildoptionen (dort ebenfalls „Kurve zeichnen…“). So
  lässt sich eine in den Bildeinstellungen gezeichnete Kurve gegen Vorlagen testen.
  Beschriftung und Ebenenname tragen den Kurznamen (`Test P50% F1200 Kurve S`; Linear, S, S+,
  Flach, Mitte+, Mitte-, Tiefen+, Lichter-, Eigene N – auch für Bildkurven). Tests:
  `tests/test_material_test_curve_axis.py`, `tests/test_material_test_draw_curve.py` u. a.

### Füllung: Schraffur, Kreuzschraffur und Offset-Füllung je Ebene

Im Ebenen-Panel unter **Füllung der Ebene**: *Füllmodus* (Keine / Schraffur /
Kreuzschraffur / Offset-Füllung), *Linienabstand* in mm (0,05–20), *Winkel* in ° (0 = waagerecht,
gegen den Uhrzeigersinn; Kreuzschraffur fügt +90° hinzu, beim Einschalten
mit 0° wird 45° vorgeschlagen), *Kontur mitlasern* und *Bidirektional*
(abwechselnde Zeilenrichtung, kürzere Leerfahrten), *Winkel-Schritt* und *Überlauf* (nur
Schraffur / Kreuzschraffur), *Füllen* (welche Objekte gemeinsam gefüllt werden) und – nur bei
Offset-Füllung – *Von innen nach außen*, unter *Kontur mitlasern* die eigene
Kontur-Einstellung (*Kontur-Leistung*, *Kontur-Tempo*, *Kontur-Durchg.*). Jede Änderung ist ein
Undo-Schritt.

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
- **Winkel-Schritt** (wie LightBurn Fill „Angle Increment“, −90…90°, Standard 0° = aus):
  bei mehreren Durchgängen schraffiert jeder weitere Durchgang um diesen Winkel gedreht –
  z. B. *Winkel* 0° und Schritt 45° bei 4 Durchgängen: 0°, 45°, 90°, 135°. Die Linien liegen
  nicht genau übereinander, tiefe Gravuren (Stempel, Schiefer, Acryl) werden gleichmäßiger
  und ohne Rillen. Kreuzschraffur dreht beide Richtungen mit. Wirkt erst ab 2 Durchgängen
  (Durchgänge der Ebene); Konturen bleiben in jedem Durchgang gleich. Im G-Code steht je
  Durchgang `; FILL ANGLE a`; Zeitschätzung und Pfadvorschau zeigen jeden Durchgang mit
  seinem Winkel, die Schraffur auf der Arbeitsfläche den ersten Durchgang. Offset-Füllung
  hat keinen Winkel, das Feld ist dort ausgegraut.
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
- **Eigene Kontur-Einstellung** (wie LightBurns Unterebene *Line* unter einer *Fill*-Ebene;
  `outline_power` 1–100 %, `outline_speed` 1–6000 mm/min, `outline_passes` 1–30, je „wie
  Ebene“ = 0, Standard): mit *Kontur mitlasern* lasert die Ebene zuerst die ganze Füllung mit
  allen ihren Durchgängen und danach alle Linien der Ebene (Konturen und offene Pfade) als
  eigener Block `; LAYER Name (Kontur)` mit eigenem `S` / `F` / Durchgängen – z. B. ein
  Namensschild schnell mit 20 % schraffieren und den Umriss mit 100 % bei 300 mm/min in
  2 Durchgängen ausschneiden, in einer Ebene. Kerf, An-/Abfahrt, Überschnitt, Haltestege,
  Rampe, Perforation und manuelle Startpunkte gelten weiter für die Kontur; ein Fokus-Schritt
  je Durchgang wird bei mehr Kontur-Durchgängen so verkleinert, dass die Absenkung in 3 mm
  bleibt. Die Felder sind nur mit Füllung und *Kontur mitlasern* bedienbar; Ebenenzeile
  („· Kontur 100 % · 300 mm/min · 2×“) und ein Live-Hinweis zeigen die Einstellung. Planer,
  Zeitschätzung und Pfadvorschau folgen dem G-Code; ein einziges `M3 I` für den Auftrag.
  Gespeichert nur, wenn gesetzt; kaputte Werte laden als „wie Ebene“; ohne eigene Werte (oder
  alle gleich der Ebene) bleiben Projekte und G-Code Byte für Byte gleich.
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
  `fill_overscan_mm`, `outline_power`, `outline_speed`, `outline_passes`) werden nur geschrieben, wenn sie vom
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
  Spitze markiert, Teillängen und „nach ca. …“ – die geschätzte Zeit bis dorthin –
  in der Anzeige).
- Wie LightBurns Vorschau: **„▶ Abspielen“** lässt die Bahn in Sendereihenfolge
  ablaufen (ab der Reglerstellung, am Ende von vorn; „❚❚ Pause“ hält an, Ziehen am
  Regler ebenso), Tempo 1× / 10× / 50× (Standard) / 200× / 1000× der geschätzten
  Echtzeit – die Zeitachse verteilt die G-Code-Zeit der Schätzung (mit Beschleunigung,
  ohne Anfahrt / Parken) nach Länge / Vorschub auf die Bewegungen.
  **„Leerfahrten“** (an) blendet die grauen Leerfahrten aus („Show traversal moves“),
  Längen und Zeit bleiben. **„Leistung“** (aus) schattiert jeden Schnitt nach seinem
  `S`-Wert („Shade according to power“: 16 Stufen von blass bis kräftig) – so sieht man
  Rampe, Steg-Pulse, eigene Kontur-Leistung, schwache Gravur-Ebenen und Bild-Graustufen
  vor dem Senden. Alles nur Ansicht für die Sitzung (nicht im Projekt gespeichert);
  im Touch-Modus sind Knöpfe ≥ 40 px und der Reglergriff 28 px groß.
- Neu gerechnet wird erst 250 ms nach der letzten Änderung und nur, solange
  die Vorschau an ist.

Bekannt: Die Bahn beginnt an der ersten Positionierfahrt (Länge 0 mm in der
Leerfahrtlänge); die Zeit rechnet Anfahrt aus der Park-Ecke und Parken
dazu (ohne Referenzfahrt/Abtasten; Höhen, Kopfposition und Versatz am Ursprung
aus dem Pi-Status, offline die Pi-Standardwerte ab X0/Y0). Sehr große Rasterjobs werden vollständig gelesen;
bei vielen tausend Zeilen kann das Neuberechnen spürbar dauern.

### Anordnen: Passmarken, Ausrichten, Verteilen, Arrays, Entlang Pfad kopieren, Verschachteln

Knopf „Anordnen“ in der Aktionsleiste (und Untermenü im Kontextmenü), Rechnen in
`lumacut_canvas/arrange.py` (Qt-frei), Oberfläche in `arrange_ui.py`. Jede Aktion ist ein
Undo-Schritt; Gruppen zählen als eine Einheit und bleiben in sich unverändert.

- **Passmarken** (Werkzeug, Alt+Umschalt+M, Werkzeugleiste und oben im Menü „Anordnen“, wie
  LightBurns *Print and Cut*, `marks.py` / `marks_ui.py`): legt das Design an zwei Marken auf
  das echte Werkstück – z. B. einen bedruckten Aufkleberbogen mit zwei Fadenkreuzen, ein schon
  graviertes Teil zum Ausschneiden oder ein schief eingelegtes Brett. Vier Tipps: **Soll 1**
  (Marke im Design, fängt an Mitten / Ecken / Knoten, kein Raster), **Ist 1** (dieselbe Marke auf
  dem Kamerascan als Hintergrund, genau dort, ohne Fang), **Soll 2**, **Ist 2** – dann werden die
  ausgewählten Objekte (ohne Auswahl alle Objekte entsperrter Ebenen) in einem Undo-Schritt
  verschoben und gedreht. Eingabe nach dem ersten Paar verschiebt nur; Rücktaste nimmt den
  letzten Punkt zurück, Esc löscht die Punkte (die Auswahl bleibt). Vorschau: blaue Kreise =
  Soll, orange Fadenkreuze = Ist, Pfeile dazwischen und gestrichelt, wohin das Design kommt.
  Ohne „Passmarken: Maßstab angleichen“ (Kontextmenü, Vorgabe aus) bleibt das Design
  maßhaltig: Mitte auf Mitte, Richtung auf Richtung, ein abweichender Abstand verteilt sich zur
  Hälfte auf beide Marken (die Meldung nennt Abstand Ist/Soll und Abweichung je Marke); an
  skaliert es zusätzlich gleichmäßig, damit beide Marken genau treffen. „Passmarken als
  Zahlen …“ nimmt Soll / Ist als X/Y in Anzeige-Koordinaten (z. B. mit dem Lineal gemessen),
  vorbelegt mit den angetippten Punkten bzw. den Ecken der Auswahl. Abgelehnt wird: Marken
  näher als 5 mm, ein Ist-Abstand mehr als 10 % neben dem Soll-Abstand (falsche Marke?) und ein
  Ergebnis außerhalb der Arbeitsfläche (es würde sonst in die Fläche geschoben). Steht die
  Startposition am Pi auf „Kopfposition“ / „Benutzer-Ursprung“, weist die Meldung darauf hin
  (für Passmarken „Absolut“ wählen). Kein neuer Projekt-Schlüssel – nur die Objekte bewegen sich.
  **Drei Marken** („Passmarken: drei Marken“ im Kontextmenü des Werkzeugs, Vorgabe aus, gilt
  für die Sitzung): nach Ist 2 noch **Soll 3** / **Ist 3** antippen (dritte Marke über Eck, z. B.
  drei Ecken des Bogens; Eingabe vorher richtet an zwei Marken aus). Maßhaltig gleicht die
  Bewegung alle drei Marken nach kleinsten Quadraten aus (die Meldung nennt die größte
  Rest-Abweichung); mit „Maßstab angleichen“ skaliert es **X und Y getrennt** – für Drucker, die
  quer etwas anders drucken als längs, was zwei Marken nicht erkennen. Ein schief eingezogenes
  Blatt (Scherung) bleibt als Rest-Abweichung stehen und wird gemeldet; gedrehte Objekte bleiben
  formtreu wie beim Skalieren am Rahmen. Abgelehnt werden zusätzlich gespiegelte Marken
  (Reihenfolge vertauscht) und für getrennte Maßstäbe Marken auf einer Linie. Der Zahlen-Dialog
  hat dafür „Drittes Paar verwenden“.
- **Ausrichten** links / mittig / rechts / oben / mittig / unten (Strg+Umschalt+←/H/→/↑/V/↓):
  mehrere Einheiten an der Auswahl-Hüllbox, ein einzelnes Objekt an der Arbeitsfläche.
- **Verteilen** waagerecht/senkrecht: gleiche Lücken, die äußeren Einheiten bleiben
  stehen (ab drei Einheiten).
- **Raster-Array …**: Spalten × Zeilen, Lücke X/Y in mm (Schritt = Auswahlgröße + Lücke).
- **Kreis-Array …**: Anzahl inkl. Original, Mitte X/Y, Winkel (360° = geschlossen, sonst
  Bogen mit Anfang und Ende), „Kopien mitdrehen“ an/aus.
- Kopien bekommen neue IDs und eigene Gruppen; läge eine Kopie außerhalb der
  Arbeitsfläche oder wären es mehr als 500, passiert nichts (Meldung in der Statuszeile).
- **Entlang Pfad kopieren …** (Alt+Umschalt+C, wie LightBurns *Copy Along Path*,
  `alongpath.py` / `alongpath_ui.py`): Objekte und einen Pfad (Linie, Pfad, Polygon, Rechteck,
  Ellipse; bei mehreren gewinnt eine offene Linie, sonst der größte) auswählen – „Anzahl“
  Kopien (2–500) der übrigen Auswahl als eine Einheit gleichmäßig auf dem Pfad, offen vom
  Anfang bis zum Ende, geschlossen mit gleichen Abständen ab „Start“ (% der Länge, 0 % = oben
  Mitte); „Mit dem Pfad drehen“ (die Auswahl gilt als nach rechts zeigend) oder aufrecht. Das
  Original bleibt, die Kopien werden ausgewählt; läge eine außerhalb der Arbeitsfläche,
  passiert nichts. Ein Undo-Schritt, Meldung mit Abstand und Pfadlänge.
- **Verschachteln …** (Alt+Umschalt+N, wie LightBurns *Nesting* / xTools „Intelligentes
  Verschachteln“, `nesting.py` / `nesting_ui.py`): legt die ausgewählten Teile platzsparend
  auf das Material – größte zuerst, ab der gewählten Ecke („Oben rechts (Nullpunkt)“,
  oben links, unten rechts/links). Bereich: das größte ausgewählte Rechteck (Material,
  bleibt stehen) oder die Arbeitsfläche; „Abstand“ zwischen den Teilen und „Randabstand“
  (je 2 mm), „Drehen“ (nicht / 90° / 45°), „Form“ (echte Form – Teile greifen ineinander –
  oder Hüllbox), „Enthaltene Objekte zusammenhalten“ (Gravur / Löcher innerhalb eines Teils
  wandern mit) und „Andere Objekte aussparen“ (nicht ausgewählte sichtbare Objekte bleiben
  frei). Rasterverfahren, Abstände garantiert (konservativ gerastert, je nach Bereich
  0,25–0,3 mm Raster); Teile, die nicht passen, bleiben stehen. Ein Undo-Schritt, Meldung mit
  belegter Fläche und Materialnutzung. Formen, Ebenen und Stege bleiben unverändert – die
  Teile werden nur verschoben / gedreht.

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

### Pfad: Boole-Operationen, Verschweißen, Versatz, Text in Pfade, Zerlegen / Kombinieren

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
- **Zerlegen** (Strg+Alt+B, wie LightBurn *Break Apart* – dessen Alt+B ist hier
  „Bogentext“): Objekte mit mehreren Teilpfaden (Text in Pfade, xTool-Import, Boole-Ergebnis,
  kombinierte Objekte) werden einzelne Objekte – Löcher bleiben bei ihrer Außenkontur (das
  „O“ bleibt ein Ring mit Loch, Inseln in Löchern werden eigene Teile), damit Füllung, Kerf und
  „innen zuerst“ gleich bleiben. „Zerlegen (jeder Teilpfad einzeln)“ trennt auch die Löcher ab;
  offene Pfade zerfallen in ihre Teilpfade. Drehung, Ebene, Gruppen und Kurvensegmente bleiben,
  jedes Teil liegt an der Stelle des Objekts im Stapel.
- **Kombinieren** (Strg+Alt+C, wie LightBurn *Combine* – Alt+C ist „Barcode“): die Auswahl wird
  je Ebene *ein* Objekt mit mehreren Ringen, geschlossene Formen (Rechteck, Ellipse, Polygon,
  Text) ein Polygon, offene (Pfad, Linie) ein Pfad. Anders als „Vereinigen“ bleiben alle
  Konturen erhalten; innen liegende werden Löcher (Gerade-Ungerade) – so lässt eine Füllung
  mit „Jedes Objekt einzeln“ das Loch eines importierten Logos frei. Überlappen sich Konturen,
  nennt die Statusleiste die Zahl („Achtung: … Überlappung(en) … „Vereinigen““). SVG / PDF /
  DXF legen jeden Teilpfad als eigenes Objekt an; nach dem Import nennt die Statusleiste
  „N Loch-Kontur(en) als eigene Objekte … „Kombinieren““ bzw. Objekte aus mehreren Teilen
  („Zerlegen“). Code: `lumacut_canvas/pathsplit.py`.
- **Schrift** (PropertyBar, sobald nur Text ausgewählt ist): Schriftart, Größe in pt
  (Geviert; skaliert die Box gleichmäßig), **F**ett, *K*ursiv und „In Pfade“. Schriftart
  und Schnitt behalten die Höhe und passen die Breite an; die letzte Wahl gilt für neue
  Texte. Gespeichert als `"bold"`/`"italic"` (nur wenn gesetzt).
- **Text-Satz** (PropertyBar neben Fett / Kursiv, wie LightBurns *Text › Align X / H-Space /
  V-Space* und xTools „Ausrichtung“ / „Zeichenabstand“ / „Zeilenabstand“): vier Knöpfe
  **links / zentriert / rechtsbündig / Blocksatz** richten die Zeilen eines mehrzeiligen Texts
  nach ihrer Laufweite aus – im **Blocksatz** wird jede Zeile außer der letzten an ihren
  Wortlücken gleichmäßig gedehnt, bis ihr letztes Zeichen (ohne Leerzeichen am Ende) auf der
  Laufweite der breitesten Zeile endet; Einzug, Zeilen ohne Leerzeichen und die letzte Zeile
  bleiben linksbündig, die Wörter behalten Unterschneidung und Zeichenabstand (auch
  Einlinien-Schriften; senkrechter Text dehnt die Lücken der Spalten bis zur längsten Spalte); **„Abstand“** (−50 … 200 % der Schriftgröße, 0 = Abstand der Schrift) fügt
  nach jedem Zeichen Platz ein bzw. rückt die Buchstaben zusammen; **„Zeilen“** (50 … 400 %,
  100 % = bisheriger Zeilenabstand 1,25 × Schriftgröße) ändert den Zeilenabstand. **¶** öffnet
  den Text mehrzeilig im Dialog (eine Zeile je Absatz; Doppelklick bearbeitet direkt auf der
  Arbeitsfläche, Enter = neue Zeile). Die Buchstaben behalten ihre Größe in mm, die Box folgt dem Umriss; fest
  bleibt die obere Kante links, mittig oder rechts je nach Ausrichtung (auch gedreht).
  Ausrichtung und Zeilenabstand sind erst ab zwei Zeilen aktiv. Ein Undo-Schritt für die
  ganze Auswahl, Pfeilschritte im selben Feld werden zusammengefasst. Wirkt auf Anzeige,
  Füllung, G-Code, SVG/PNG-Export, „In Pfade“, Seriennummern und variablen Text. Gespeichert
  als `"letter_spacing"` / `"line_spacing"` / `"align"` nur, wenn gesetzt – Texte ohne diese
  Felder geben denselben Umriss und denselben G-Code wie bisher. Code:
  `lumacut_canvas/text_ui.py`, `shape_paths.text_path`.
- **Text verschweißen** (PropertyBar-Knopf mit zwei verbundenen Kreisen neben „Zeilen“, wie
  LightBurns *Text › Weld*): überlappende Buchstaben eines Textobjekts – Schreibschrift,
  negativer Zeichenabstand, enge Zeilen – werden zu einem Umriss vereinigt
  (Nicht-Null-Regel, Kurven auf ≈ 0,01 mm abgeflacht). Kein Schnitt quer durch die
  Buchstaben, ein ausgeschnittener Name bleibt ein Teil, Überlappungen werden mitgefüllt
  statt ausgespart; Innenräume („o“, „A“) bleiben Löcher, solange kein anderer Buchstabe sie
  überdeckt. Der Text bleibt bearbeitbar (Schrift, Größe, Satz), die Box ändert sich nicht.
  Ein Undo-Schritt für die ganze Auswahl. Wirkt auf Anzeige, Füllung, G-Code, SVG/PNG-Export,
  „In Pfade“ und Seriennummern. Gespeichert als `"weld": true` nur, wenn gesetzt. Code:
  `shape_paths.weld_path`, `lumacut_canvas/text_ui.py`.
- **Einlinien-Schrift** (PropertyBar, Auswahl links vor der Schriftart, wie LightBurns
  *Single-Line Fonts* und xTools Einlinien-Schriften): „Umrissschrift“ (die gewählte
  Schriftart), **„Einlinie (Sans)“** oder **„Einlinie (Schreibschrift)“**. Bei einer
  Einlinien-Schrift ist jeder Buchstabe ein einzelner offener Strich (Hershey-Schriften
  *Roman Simplex* / *Script Simplex*), den der Laser genau einmal abfährt – schnell, dünn und
  gleichmäßig für Beschriftungen, Skalen, kleine Nummern, Unterschriften und Stifte; ein
  Umriss-Text wird dagegen doppelt umfahren oder flächig gefüllt. Umlaute, ß, Akzente, €,
  °, Gedankenstrich, „Anführungszeichen“ und … sind dabei, andere Zeichen erscheinen als „?“
  (die Statusleiste nennt sie). Größe, Kursiv (schräg gestellt), Abstand, Zeilen,
  Ausrichtung und ¶ wirken wie gewohnt; Fett und Verschweißen sind aus. Einlinien-Text wird
  nie gefüllt – auch auf einer Füll-Ebene wird er als Linie gelasert – und ist keine Maske
  zum Zuschneiden; „In Pfade“ macht daraus einen offenen Pfad mit einem Teilpfad je Strich.
  Die letzte Wahl gilt für neue Texte, „Umrissschrift“ führt zur zuletzt gewählten
  Schriftart zurück; ein Undo-Schritt für die ganze Auswahl. Gespeichert als Schriftname
  (`"font": "LumaCut Einlinie"` / `"LumaCut Einlinie Schreibschrift"`), kein neuer
  Schlüssel. Code: `lumacut_canvas/linefont.py` (Glyphen in `linefont_data.py`),
  `shape_paths.line_text_path`, `model.is_closed_shape`, `lumacut_canvas/text_ui.py`.
  **Kerning-Paare eigener SVG-Fonts**: die `<hkern>`-Paare einer geladenen SVG-Schrift (`u1` /
  `u2` mit Zeichen, `U+0041` oder `U+0041-005A`, `g1` / `g2` mit `glyph-name`s, `k` in
  Schrifteinheiten) rücken Paare wie „AV“ oder „To“ zusammen – in Zeilen, Ausrichtung,
  Blocksatz, Textbox, Bogentext / Text auf Pfad und G-Code; zusammengesetzte Umlaute nutzen
  die Paare ihres Grundbuchstabens („ÄV“ wie „AV“). Die Statusleiste nennt beim Laden die
  Zahl der Paare. Eingebaute Schriften, `.jhf` und senkrechter Text bleiben ohne Kerning
  (`linefont.kerning`).
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
- **xTool `.xcs` / `.xs`**: Pfade, Rechtecke (mit Eckenradius – bleibt änderbar), Kreise/Ellipsen, Linien,
  Polygone, Text (als Glyphenkonturen, sonst Textobjekt) und Bitmaps der ersten Arbeitsfläche;
  Laserwerte werden nicht übernommen, unbekannte/ausgeblendete Objekte gezählt und übersprungen.
  Tabelle und Grenzen: [Anforderungen §9.2](../../docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md).
- **Import-Einstellungen** (*Datei › Import-Einstellungen …*, wie LightBurns *Auto-close
  tolerance* der DXF-Import-Einstellungen und dessen Import eines SVG-Pfads mit Löchern als
  *eine* Form): drei Schalter, **standardmäßig aus** (ohne Häkchen bleibt jeder Import wie
  bisher – jede Teilkontur ein eigenes Objekt, gleicher G-Code). „Doppelte Konturen löschen“
  übernimmt übereinanderliegende gleiche Konturen der Datei nur einmal (wie „Duplikate
  löschen“), „Offene Pfade verbinden“ fügt lose Strecken mit Enden ≤ Toleranz (Standard
  0,05 mm, 0,001–2 mm) zu Pfaden zusammen – geschlossene werden Polygone, ineinanderliegende
  ein Polygon mit Loch (wie „Pfade verbinden“) –, „Löcher mit Außenkontur kombinieren“ fasst
  geschlossene Konturen, die in einer anderen liegen, mit ihr zu *einem* Objekt mit Loch
  zusammen (Inseln in Löchern bleiben eigene Objekte; wie „Kombinieren“), damit „Jedes Objekt
  einzeln“ das Innere eines „O“ nicht mitfüllt. Reihenfolge: Duplikate, Verbinden, Löcher. Gilt
  für SVG / DXF / PDF / AI / EPS / xTool (Strg+I und Drag & Drop), nur für die Objekte der
  Datei, nie für Bilder oder Codes; Ebene und Import-Gruppe bleiben, ein Rückgängig-Schritt
  „Importieren“. Die Statusleiste nennt, was geändert wurde („beim Import: 1 Duplikat(e)
  gelöscht, 8 offene Form(en) verbunden → 1 geschlossen …“). Die Wahl wird gespeichert
  (QSettings `import/…`); *Alles aus* stellt den Standard wieder her.
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
  Laserpunkten); *Zurücksetzen* stellt „unverändert“ wieder her, **Auto-Tonwert** setzt Schwarz-
  und Weißpunkt auf den Tonwertumfang des (geschärften) Bildes ohne je 0,5 % Ausreißer – exakt
  linear von Schwarz bis Weiß gestreckt – und Helligkeit / Kontrast auf 0 (Gamma und Schärfen
  bleiben; erneutes Klicken ändert nichts, flaches Bild: 0 / 255). Die **Kurve** (Gradationskurve, wie
  LightBurn / Photoshop „Curves“) wirkt nach Schwarz- / Weißpunkt: über dem Histogramm des
  Bildes (nach Tonwertkorrektur) Punkte per Klick setzen und ziehen, Rechtsklick / Doppelklick
  / *Entf* entfernt einen Punkt (Endpunkte springen in ihre Ecke zurück), höchstens 16 Punkte;
  die Kurve verläuft monoton ohne Überschwinger durch alle Punkte. Vorlagen: Linear, Kontrast
  verstärken (S-Kurve) / stark verstärken / verringern, Mitteltöne aufhellen / abdunkeln,
  Schatten aufhellen (dunkle Holzstellen), Lichter abdunkeln (helle Flächen gravieren); die
  Histogramm-Zeile nennt die aktive Kurve. Auto-Tonwert lässt die Kurve unverändert,
  *Zurücksetzen* stellt sie auf linear. Gespeichert wird die Kurve nur, wenn sie nicht linear
  ist (ältere Dateien unverändert). Die Anpassung gilt für alle Modi
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
  etwa die halbe Strahlbreite, höchstens der Linienabstand; 0 = aus. **Scan-Winkel** (wie
  LightBurn „Scan Angle“, −90…90°, gegen den Uhrzeigersinn; 0 = Zeilen entlang X, 90 = entlang Y)
  lasert die Rasterzeilen schräg – z. B. entlang der Holzmaserung oder gegen sichtbare Streifen:
  das Bild wird in einem um den Winkel gedrehten Raster im Linienabstand gerechnet und jede Zeile
  als schräge `G1`-Strecke (X und Y zugleich) ausgegeben, auf das Bild gekürzt; Overscan,
  Scan-Versatz und Bidirektional laufen entlang der Zeile (am Rand der Arbeitsfläche gekürzt), der
  Halbtonwinkel bleibt auf dem Werkstück wie eingestellt, 3D-Tiefe geht ebenso. **Winkel-Schritt je
  Durchgang** (LightBurn „Angle Increment“, nur bei mehreren Durchgängen) dreht jeden weiteren
  Durchgang um den Schritt weiter (z. B. 90° = Kreuzraster für gleichmäßigere Flächen). Die
  Live-Vorschau zeigt den ersten Durchgang im gedrehten Raster, in Canvas-Lage zurückgedreht.
  Winkel 0 = bisherige Ausgabe (ältere Dateien unverändert). Bilder werden im
  Auftrag vor den Vektor-Ebenen graviert.
  **Laserpunkt simulieren** (unter der Vorschau, mit **Punktgröße** 0,01…1 mm, Vorgabe 0,08 mm,
  für alle Bilder gespeichert): die Vorschau wird zur Lupe auf die Bildmitte (höchstens
  600 × 600 Bildpunkte) und zeigt die gelaserten **Spuren in der echten Strahlbreite** statt
  eines Pixels je Laserpunkt – jede Rasterzeile als Spur entlang der Scan-Richtung (Gauß-Strahl,
  eine Linie mit voller Leistung ist genau die Punktgröße breit), überlappende Spuren werden
  dunkler, die Punktbreitenkorrektur kürzt die Strecken wie im G-code. So sieht man vor dem
  Lasern **helle Streifen**, wenn der Linienabstand größer als der Punkt ist, und ein dunkles,
  matschiges Foto, wenn die Spuren stark überlappen; der Hinweis nennt die passende DPI-Zahl,
  **Als Linienabstand** setzt den Linienabstand auf die Punktgröße (die Empfehlung von LightBurn
  und xTool). Gilt für alle Modi, Scan-Winkel, alle Durchgänge und die Brennsumme. Punktgröße =
  gemessene Breite einer gelaserten Linie mit den eigenen Werten (Material, Leistung und
  Geschwindigkeit werden nicht modelliert). Nur Vorschau – Projekt und G-code bleiben
  unverändert. Code: `src/lumacut_import/spot_preview.py`.
  **Länglicher Diodenpunkt**: neben der Punktgröße **X** gibt es eine eigene Größe **Y** (beide in
  Maschinenlage, z. B. 0,08 × 0,06 mm – die meisten Diodenlaser brennen keinen runden Punkt, der
  Emitter ist ein Streifen). Solange Y = X ist, folgt Y der X-Größe (runder Punkt wie bisher).
  Der Strahl wird dann ein elliptischer Gauß, im Raster jedes Durchgangs um dessen Scan-Winkel
  gedreht: die Spur ist **quer zur Scan-Richtung** so breit wie der Punkt in dieser Richtung
  (0° = Y-Größe, 90° = X-Größe, dazwischen √(X²·sin² + Y²·cos²)). Streifen-/Überlappungs-Hinweis
  und **Als Linienabstand** richten sich nach dieser Spurbreite (beim gezeigten Durchgang; alle
  Durchgänge / Brennsumme: der erste), der Hinweis nennt außerdem die Spurbreite bei um 90°
  gedrehtem Scan-Winkel, wenn sie sich um mindestens 15 % unterscheidet. Y wird wie X für alle
  Bilder gespeichert (`image_preview/spot_y_mm`; ältere Einstellungen ohne Y = runder Punkt).
  **Ausschnitt / Lupe verschieben**: große Bilder zeigt die Vorschau als Ausschnitt von höchstens
  600 × 600 Laserpunkten, die Laserpunkt-Simulation als Lupe – bisher immer aus der Bildmitte.
  Jetzt lässt sich der gezeigte Bereich mit Maus oder Finger **ziehen** (wie eine Karte, der
  Inhalt folgt dem Zeiger), **Doppelklick** oder **Mitte** (unter der Vorschau, 44 px im
  Touch-Modus) setzt ihn zurück auf die Bildmitte. Die Mitte wird in mm neben der Bildmitte in
  Canvas-Lage geführt und am Bildrand begrenzt; sie folgt Drehung des Bildes, Scan-Winkel, allen
  Durchgängen / Brennsumme (alle mit derselben Mitte) und Linienabstand. Der Text unter der
  Vorschau nennt die Lage („Lupe 12.0 mm links, 6.0 mm über der Bildmitte“). Nur Vorschau –
  nicht gespeichert, Projekt und G-code bleiben unverändert.
- **Bild nachzeichnen** (*Datei › Bild nachzeichnen…*, *Alt+T*, wie LightBurn „Trace Image“):
  wandelt das ausgewählte Bild in Vektorkonturen. Schwellwert (dunkler = Kontur; Startwert aus den
  Bildeinstellungen), Invertieren, Glättung (Weichzeichnen vor dem Schwellwert), Toleranz
  (Vereinfachung in mm) und Mindestfläche (Flecken/kleine Löcher ignorieren), mit Live-Vorschau.
  Ergebnis: Polygone auf den Pixelkanten, Löcher als Ringe (Schraffur, Kerf und „innen zuerst“
  behandeln sie richtig), mehrere Teile gruppiert, deckungsgleich über dem Bild in der aktiven
  Ebene; **ein** Rückgängig-Schritt, auf Wunsch inkl. Löschen des Bildes. Sehr verrauschte Bilder
  werden mit Hinweis abgelehnt (Glättung/Mindestfläche erhöhen). Code:
  `src/lumacut_import/trace.py` (Qt-frei, OpenCV + shapely), Dialog `trace_qt.py`.
- **Bild mit Form zuschneiden** (*Pfad › Bild mit Form zuschneiden*, auch *Datei* und
  Kontextmenü „Pfad“ – im Touch-Modus lange drücken; *Strg+Alt+M*; wie LightBurns *Tools › Crop
  Image* / xTool „Zuschneiden“): ein Bild und darüber eine oder mehrere geschlossene Formen
  auswählen (Rechteck, Ellipse, Vieleck / Stern, Text, geschlossener Pfad). Außerhalb der Form
  wird das Bild **durchsichtig und nie gelasert** (auch mit *Negativ*, Bildanpassung, Skizze,
  Scan-Winkel und 3D), das Bild schrumpft auf den Rest – gleiche Auflösung und Drehung, Rahmen,
  Zeitschätzung und Auftrag nur über den sichtbaren Teil. Mehrere Formen und Löcher gelten wie
  eine Füllung (Gerade-Ungerade): Kreis im Rechteck = Ring, Text behält seine Innenräume
  („o“, „A“). Die Formen bleiben erhalten (z. B. um das Foto-Untersetzer-Rund danach
  auszuschneiden; *Entf* löscht sie), **ein** Rückgängig-Schritt stellt das Originalbild wieder
  her. Zweimal zuschneiden schneidet weiter. Gespeichert wird das zugeschnittene Bild als
  PNG mit Alphakanal – keine neuen Datei-Schlüssel; Bilder ohne Zuschnitt bleiben bytegleich.
  Code: `src/lumacut_canvas/imagecrop.py`, `imagecrop_ui.py`.
- **Maske auf Bild anwenden / Bildmaske lösen** (*Pfad › Maske auf Bild anwenden*, auch *Datei*
  und Kontextmenü „Pfad“; *Strg+Alt+Umschalt+M*; wie LightBurns *Tools › Apply Mask to Image* /
  *Remove Mask*): die zerstörungsfreie Variante des Zuschneidens. Ein Bild und darüber eine oder
  mehrere geschlossene Formen auswählen – die Formen werden zur **Live-Maske** des Bildes
  (Gerade-Ungerade wie beim Zuschneiden). Außerhalb wird das Bild durchsichtig und nie gelasert,
  die **Bildpunkte bleiben aber erhalten** und die Box behält ihre Größe. Die Maske wandert beim
  Verschieben, Skalieren und Drehen mit dem Bild. *Bildmaske lösen* macht das Bild wieder ganz
  und gibt die Maskenform als bearbeitbare geschlossene Form auf ihrer Ebene zurück – ändern
  oder verschieben und neu anwenden. Je **ein** Rückgängig-Schritt; Bilder auf gesperrten Ebenen
  und Masken auf gesperrten Ebenen werden nicht angefasst. Zuschneiden eines maskierten Bildes
  übernimmt die Maske fest. Gespeichert werden die Maskenringe im Bild (`"mask"`, `"mask_layer"`,
  nur bei maskierten Bildern) – Bilder ohne Maske bleiben bytegleich. Code:
  `src/lumacut_canvas/imagemask.py`, `imagemask_ui.py`.
- **Mehrere Masken / Bereich im Bild ausblenden** (*Pfad › Bereich im Bild ausblenden*, auch
  *Datei* und Kontextmenü „Pfad“; *Strg+Alt+Umschalt+H*): *Maske auf Bild anwenden* auf ein Bild,
  das schon eine Maske hat, **verkleinert** sie – sichtbar bleibt nur die Überschneidung von alter
  Maske und neuer Form (zwei Masken übereinander). *Bereich im Bild ausblenden* ist die
  **umgekehrte Maske**: die Fläche der Formen wird durchsichtig und nie gelasert, der Rest bleibt
  (Logo, Datumsstempel oder Hintergrundecke aus einem Foto nehmen); auf einem maskierten Bild
  kommen weitere Löcher dazu. Beides lässt sich beliebig kombinieren. Sind **mehrere Bilder**
  ausgewählt, bekommt jedes Bild, das die Formen berühren, sie im selben Rückgängig-Schritt;
  unberührte Bilder bleiben, wie sie sind (die Statuszeile nennt sie). Gespeichert wird weiter
  nur ein Ringsatz (Außenkontur + Löcher) im Bild – keine neuen Datei-Schlüssel, eine erste
  Maske bleibt bytegleich. *Bildmaske lösen* gibt die zusammengesetzte Form zurück (nach dem
  Ausblenden: Bildrechteck mit Loch).
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
