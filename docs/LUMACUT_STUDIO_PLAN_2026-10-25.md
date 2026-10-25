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
