# LumaCut Studio

Eigene Design- und Steuersoftware für die LumaCut-Maschine (Tauri 2, Windows; Android-Tablet geplant). Ziel: LightBurn ablösen. Plan und Fahrplan: [docs/LUMACUT_STUDIO_PLAN_2026-10-25.md](../../docs/LUMACUT_STUDIO_PLAN_2026-10-25.md).

## Was es heute kann

- Editor: Rechteck, Ellipse, Linie, Freihand, Text, SVG-Import, Bilder (JPG/PNG/WebP), Ebenen mit Leistung/Vorschub/Durchgängen, Materialbibliothek, Projekte speichern/laden, Autosave, Rückgängig/Wiederholen.
- Planung: Vektorpfade und Schwarzweiß-Raster (Schwellwert, Floyd-Steinberg) in Ebenenreihenfolge, 30-mm-Safezone wird erzwungen.
- Marlin-G-Code (`marlin-postprocessor.mjs`): ein `M3 I` pro Auftrag, S 0–255 in jedem G1, Leerfahrten mit G0. Homing, Abtasten, Fokus und Parken übernimmt der Pi.
- Reiter **Maschine** (nur in der installierten Windows-App): Status, Referenzieren, Joggen, Abtasten (G30), Licht/Abluft, „Projekt senden & Ein-Klick-Start“, Abbruch, Notstopp. Die Anfragen gehen über die Rust-Befehle `read_pi_status`, `pi_action` und `pi_upload_job` an die Pi-API (Port 8080). Nur lokale IP-Adressen sind erlaubt, und die Aktionen sind auf eine feste Liste beschränkt.
- Kamera: Live-Ansicht und Homographie-Kalibrierung über vier Referenzpunkte (noch ohne Kachel-Scan).

## Noch nicht fertig

Graustufen-Raster mit Overscan, DXF/PDF-Import, Node-Editing, Kamera-Kachel-Scan, Objekterkennung, Bereichs-Abtastung mit Höhenmesh, Tablet-Build, signierte Updates. Die Y-Ausrichtung (Studio zeichnet Y nach unten) muss an einem Testmotiv mit der Maschine abgeglichen werden.

## Entwickeln

```bash
npm install
npm run test:unit      # Geometrie, Planer, Postprozessor, Kalibrierung
npm run test:ui        # ausgelieferte Oberfläche in Chrome/Edge
npm run build:windows  # NSIS-Installer (braucht Rust + Tauri CLI)
```

Ohne Build: `index.html` direkt in Chrome/Edge öffnen (ohne Maschinen-Reiter). Der Windows-Installer entsteht in GitHub Actions (`lumacut-studio-windows.yml`). Abnahmekriterien: [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md).
