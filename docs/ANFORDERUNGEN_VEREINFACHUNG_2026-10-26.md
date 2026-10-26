# LumaCut: Vereinfachung Windows- und Android-App (2026-10-26)

**Ziel:** Beide Apps so einfach machen, dass ein Neuling Material wählt, Motive platziert und den Auftrag startet. Alles andere passiert automatisch.

Dieses Dokument ist die gemeinsame Quelle für Grok-Agents und Claude. Änderungen bitte hier und in den Commit-Nachrichten dokumentieren.

## 1. Gewünschter Ablauf (ein Klick)

1. Material auswählen (Stärke, Einstellungen kommen aus der Pi-Datenbank).
2. Motive platzieren und bearbeiten.
3. **Auftrag starten** – fertig.

Der Rest läuft automatisch:
- Referenzfahrt (XY zuerst, dann Z, Rückzug)
- Schnelles Probing / Höhenmesh (immer, keine Auswahl)
- Fokus
- Job
- Parken

**Kein** manueller Schritt für Referenzieren oder „mit/ohne Probing“. Probing ist immer dabei und soll schnell sein.

## 2. Nullpunkt und Achsen

- **X/Y 0,0 ist oben rechts** (Seite der Endschalter / Tür auf der anderen Seite).
- Bisherige Darstellung (0,0 unten links) ist falsch für diese Maschine.
- Arbeitsfläche 360 × 340 mm, Safezone 30 mm bleibt intern und unsichtbar.

## 3. Kamera-Scan

- Optional, ausgelöst durch einen **einzigen Button** in beiden Apps.
- Kein Pflicht-Schritt im normalen Auftrag.
- Scan bei fester Höhe, Kachelweise, Ergebnis als Hintergrund zum genauen Platzieren.

## 4. Materialdatenbank auf dem Pi

- Materialliste und Einstellungen (Leistung, Geschwindigkeit, Durchgänge, Z-Schritt) liegen auf dem Pi.
- Windows-App, Android-App und Pi-Web-UI nutzen dieselbe Quelle.
- Änderung in einer App gilt für alle.

## 5. UI-Aufräumen (Windows + Android)

- Weniger Einstellungen und Buttons auf der Hauptansicht.
- Große, klare Aktionen: Material, Design, Start.
- Erweiterte Optionen (Kerf, Haltestege, Füllung etc.) hinter „Mehr“ oder in einem eigenen Bereich.
- Touch-freundlich, responsiv, für Neulinge verständlich.

## 6. Zusammenarbeit

- **Kommunikation über GitHub** (Commits, dieses Dokument, Issues/PRs falls nötig).
- Agents und Claude ändern keine Dateien des anderen ohne Absprache.
- Vor jedem Push: `git pull --rebase origin main`.
- Kleine, klare Commits mit Bezug auf dieses Dokument.

## 7. Offene Punkte / Zuordnung

| Thema | Zuständig | Status |
|---|---|---|
| Ein-Klick-Auftrag (Homing + Probing + Fokus + Job) | Machine + Scan Probe | offen |
| Nullpunkt oben rechts | Canvas + Machine | offen |
| Kamera-Scan als Button | Scan Probe | offen |
| Materialdatenbank auf dem Pi | Materials + Machine | offen |
| Cleaner UI Windows | Canvas | offen |
| Cleaner UI Android | (Claude / Android-Agent) | offen |

## 8. Nächste Schritte

1. Pi: Material-API und Speicherort definieren und dokumentieren.
2. Studio: Hauptansicht aufräumen, Start-Button macht den kompletten Ablauf.
3. Nullpunkt-Korrektur in Canvas und G-Code.
4. Android: gleiche Vereinfachung und Anbindung an die Pi-Materialdatenbank.
