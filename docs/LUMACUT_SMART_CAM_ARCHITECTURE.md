# LumaCut CNC Smart CAM — Zielarchitektur

Status: Spezifikation, **nicht implementierte Funktion**. Aktuell ist nur Einzelpunkt-G30/Fokus vorhanden.

## Zielworkflow: genau ein Klick in LightBurn
1. LightBurn erzeugt den gesamten Auftrag; Pi empfängt erst den vollständigen G-Code als **Spool** (keine Ausführung während des Empfangs).
2. Marlin-kompatiblen G-Code normalisieren und validieren; Bounding-Box aller Schnitt-/Gravierpfade einschließlich Kreisbögen und Rasterfahrten bestimmen; Koordinatensystem, Layer/Passwechsel und Laserbefehle erhalten.
3. Nach vollständigem Eingang, ohne Laserleistung: G28 X/Y, G28 Z, Z-Rückzug. Am Auftragsbeginn immer neu referenzieren.
4. Materialfläche/Trägerplatte getrennt kalibrieren; Tastspitzen-Offset X/Y/Z anwenden. Messtaster prüft adaptives Raster über tatsächliche Motivfläche, mit Kantenabstand und Kollisionsprüfung.
5. Höhenkarte erstellen; interpolieren, Unsicherheit begrenzen, steile Sprünge und fehlende Probe als Fehler zurückmelden.
6. Planen: pro Bewegung Fokus-Z aus Höhenkarte und Materialprofil. Graviervorschub an mechanische Z-Nachführgrenze anpassen.
7. Schnittmodus: Passanzahl, Fokus-Vertiefung je Pass, minimaler Düsen-/Tasterabstand, Eindringweg und Materialprofile; LightBurn Z-step entweder übernehmen **oder** Pi-seitig generieren, nie doppelt ausführen.
8. Auftrags-GCode nach Prüfung in vollständige XYZ+PWM-Fahrten umsetzen, saubere M3 I/M5 I-Sequenz, M400-ACK und Fortschrittsstatus.
9. Laser aus, Z auf Parkhöhe, X0/Y0. Danach bereit für nächsten Auftrag.

## Hardware & Grenzen
- SKR Mini MZ 1.0 / Marlin 2.1.2.9, Pi 400, X 390 / Y 370; erste 30 mm an beiden Achsen als freie Homing-Zone.
- LaserTree LT-80W-AA-Pro, Standard-Fokusabstand 7 mm einstellbar.
- Mechanischer Taster misst nur punktuell; darf nicht über Löcher, Kanten oder freie Luft fahren. Proben außerhalb des Werkstücks werden übersprungen, nicht angefahren.
- Die Materialdicke ist nur aus Boden-Z-Referenz und Oberflächen-Z ableitbar, wenn die Höhe des Trägertischs/Opferbretts bekannt ist.
- Werkstückkontakt, Laser-Fokus und maximale zulässige Kopfzustellung sind verschiedene Koordinatensysteme und dürfen nicht verwechselt werden.
- Zustellung des Fokus ist keine Garantie für Schnitttiefe oder gegen Verkohlung.
- Autonomes Maschinenprogramm darf kein freigegebenes Laser-PWM-Signal während der Rastervermessung erzeugen.

## LightBurn-Integration
Die vorhandene TCP-Bridge verarbeitet G-Code derzeit zeilenweise. Ohne komplettes Spooling kennt sie die Jobgrenzen erst, wenn bereits Bewegung stattfand; deshalb kann sie keine sichere automatische Motivflächenabtastung vor dem Start ausführen.
Für die vollständige Auto-Sequenz ist ein ACK-korrekter Spool- und Ausführungsmodus nötig (oder LightBurn "Save GCode" → Upload an Pi als Zwischenschritt). Kein Fake-ok, solange der Stream Fehler hat.

## Windows-Alternative
Nur falls LightBurn-Integration nicht ausreichend zuverlässig ist: Desktop-CAM mit SVG, DXF, PDF, Bilddateien; DWG mit gesondertem Konverter/Lizenzprüfung. CAM-Funktionen: Layers, Text, Raster/Dithering, Schnitt/Gravur, Vorschau, Offsets, Tabs/Bridges, Nesting, Materialprofil, adaptive Höhenkarte, Passplanung, Jobqueue. Pi bleibt alleiniger Motion Executor; gleiche G-Code-IR und API.

## Entwicklungsphasen
1. G-Code-Spooler, Geometrieparser, Tests für arc/raster/layers, automatische G28.
2. Adaptive Rasterabtastung und Interpolation, Probe-Sicherheitsfälle, Oberfläche-gegen-Boden.
3. XYZ-Fokusnachführung und geschwindigkeitsangepasste Bewegung; simulierte Tests.
4. Multi-Pass-Fokusverschiebung ohne doppelte LightBurn-Z-Korrektur, Materialprofile, Teststücke.
5. Windows-Client erst nach bewiesener Notwendigkeit.
