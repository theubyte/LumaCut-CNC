# LumaCut Studio – Vollständiger Plan (Stand 25.10.2026)

## Ziel
Eigene Windows-Software (Tauri-basiert), die mindestens so gut wie LightBurn und besser zugeschnitten ist als xTool Creative Space.  
Vollständig auf die LumaCut-Hardware abgestimmt (Raspberry Pi 400 + BTT SKR Mini MZ V1.0 mit Marlin).  
Langfristig LightBurn ersetzen. Später auch Handy-/Tablet-App.

## Hardware-Kontext (verbindlich)
- Arbeitsfläche nutzbar: ca. 360 × 340 mm (X30–390 / Y30–370)
- 30 mm L-förmige Safezone bleibt **intern und unsichtbar**
- Homing: XY zuerst, dann Z, Rückzug standardmäßig 20 mm
- Kamera fest am Laserkopf
- Z-Taster für Probing (G30)
- Laser: PA1 PWM, M3 I, S0–255
- Fokus standardmäßig 7 mm
- Parkpunkt: X0 / Y0

## Kamera & Scan
- Kamera sitzt am Laserkopf und ist nicht hoch genug für ein Einzelbild der ganzen Fläche.
- Scan erfolgt durch Abfahren der Arbeitsfläche bei **fester Höhe**.
- Einzelbilder werden zu einem scharfen, maßgenauen Gesamtbild zusammengesetzt.
- Ergebnis dient als präzise Positionsreferenz für den Nutzer.

## Probing & Höhenmapping
- Nach dem Scan werden platzierte Objekte (Viereck, Kreis, freie Formen) automatisch erkannt oder manuell markiert.
- Der Laser probe **nur diese Bereiche** automatisch.
- Jeder Bereich bekommt sein eigenes Höhenmesh.
- Adaptive Fokuskorrektur pro Region während des Jobs.
- Einzel-Probe und manuelle Punkte bleiben möglich.

## Software-Features (vollständig)

### Design & Editor
- Vektor-Werkzeuge (Rechteck, Kreis, Polygon, Text, Freihand, Node-Editing)
- Bildimport + Tracing
- Raster-Gravur mit mehreren Modi
- Ebenen mit eigenen Parametern (Leistung, Geschwindigkeit, Durchgänge)
- Materialbibliothek
- Snap, Align, Array, Gruppieren

### Kamera & Positionierung
- Kachel-Scan bei fester Höhe
- Automatische Objekterkennung
- Manuelles Markieren von Probe-Bereichen

### Maschinensteuerung
- Live-Status (Position, Homed, Laser, Fortschritt)
- Homing (XY zuerst), Jog, Park, Not-Aus
- Direkte Anbindung an den Pi über bestehende API
- Safezone intern und unsichtbar

### Workflow
1. Scan der Arbeitsfläche
2. Objekte erkennen / markieren
3. Auto-Probe der Bereiche
4. Fokus setzen
5. Job starten
6. Park

### UI
- Dunkles, klares Design
- Zentrale Canvas mit Scan-Bild und Objekten
- Linke Leiste: Ebenen + Materialien
- Rechte Leiste: Maschinenstatus + große Aktions-Buttons
- Weniger überladen als LightBurn, mächtiger als xTool

## Vergleich zu xTool / LightBurn
- Besserer vollflächiger Scan als xTool-Einzel-Snapshots
- Gezieltes Multi-Bereich-Probing mit eigenen Höhenmeshes
- Adaptive Höhenkorrektur pro Objekt
- Maschinenkenntnis von Anfang an verdrahtet
- Klare, aber vollständige Oberfläche

## Nächste Schritte
- Erste funktionsfähige Version auf dem bestehenden Tauri-Gerüst umsetzen
- Maschinen-API einbinden
- Scan- und Probe-Workflow vorbereiten
- Alles auf `main` mit klaren Commit-Messages

## Mockup-Konzepte
Die folgenden Konzepte wurden visualisiert:
- Hauptansicht mit gescanntem Bild und erkannten Probe-Bereichen
- Scan-Fortschritt mit Kacheln
- Auto-Probe-Workflow
- Maschinensteuerung (Home, Probe, Fokus, Start, Park)

Alle Änderungen und dieser Plan liegen auf `main`, damit weitere Entwicklung (auch durch Claude Code) nachvollziehbar bleibt.

---

## Architekturentscheidungen und technische Randbedingungen (Ergänzung 25.10.2026)

Vorschläge aus der Code-Analyse. Sie sind noch nicht alle umgesetzt.

1. **Eine Codebasis für Windows und Tablet.** Studio ist eine Tauri-2-App, und Tauri 2 baut auch für Android. Dieselbe Oberfläche läuft mit einer Touch-Ansicht auf dem Tablet, statt eine zweite App zu schreiben.
2. **Der Pi ist der einzige Ort mit Maschinenwissen.** Die Apps schicken langfristig einen strukturierten Auftrag (Ebenen, Pfade, Graustufen-Raster, Abtastbereiche). Der Pi erzeugt daraus die Fahrbefehle und setzt Safezone, Fokus, Höhenkorrektur und Overscan um. Heute schickt Studio noch Marlin-G-Code (`marlin-postprocessor.mjs`), den der Pi Zeile für Zeile prüft.
3. **Durchsatz zum SKR ist das größte Risiko für die Rastergravur.** Heute ist genau eine Zeile unterwegs, bis das `ok` kommt. Zuerst messen. Dann mehrere Zeilen gleichzeitig senden (`ADVANCED_OK` ist aktiv), größere Firmware-Puffer und gleiche Pixel zu einem Segment zusammenfassen. Reicht Marlin danach nicht, ist das eine eigene Grundsatzentscheidung.
4. **Höhenmesh ohne Firmware-Änderung.** Der Pi tastet je Bereich ein Raster ab, mit Randabstand, damit die Tasterspitze nicht über die Kante fährt. Beim Ausführen rechnet er Z pro Segment ein und teilt lange Linien auf. Die Z-Achse (max. 9 mm/s) begrenzt, wie schnell die Höhe nachgeführt werden kann.
5. **Taster nur auf Material.** Messpunkte, bei denen die versetzte Tasterspitze (X −23 / Y +15 mm) außerhalb des Werkstücks oder über Löchern läge, werden übersprungen und nie angefahren. Abtastung immer mit abgeschaltetem Laser.
6. **Live-Status und Kopplung.** Für das Tablet braucht der Pi eine Push-Verbindung (WebSocket/SSE) statt Abfragen und vor dem WLAN-Einsatz eine Gerätekopplung (heute kein Zugangsschutz).
7. **Kamera.** Aufnahme und Kachel-Scan gehören auf den Pi (fester Z, bekannte Positionen), das Zusammensetzen ebenfalls. Studio zeigt das Ergebnis maßgenau an. Die vorhandene Homographie-Kalibrierung (`camera-calibration-core.mjs`) ist der Startpunkt. Offen: Kameramodell und Anschluss (USB oder CSI).

Reihenfolge: (1) Pi-Kern (Job-Format, Streaming-Messung, Live-Status, Pause/Abbruch, Kopplung) → (2) Studio als Hauptwerkzeug (Graustufen mit Overscan, Materialbibliothek, Vorschau mit Zeit, Text, SVG/DXF/PDF) → (3) Kamera-Scan → (4) Objekterkennung und Bereichs-Abtastung mit Mesh → (5) Tablet-Build.
