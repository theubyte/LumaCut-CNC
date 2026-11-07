# LumaCut Studio für Windows: nativ

Projekt: `software/lumacut-native` (Zweig `windows-native`). In Visual Studio: Ordner öffnen, CMake-Voreinstellung
`release` (`CMakePresets.json`), Qt 6.10.3 MSVC liegt unter `C:\Qt` (per `aqtinstall`, ohne Konto).

Die Tauri-Fassung (Zweig `windows-app`) ist Referenz für Bedienung und Abläufe und wird nicht weitergebaut,
siehe `docs/WINDOWS_APP_TAURI_REFERENZ.md` für Informationsarchitektur und Designregeln, die weiter gelten.
Die älteren Stände `software/lumacut-studio`, `software/lumacut-studio-native` und `software/lumacut-windows` sind überholt.

## Technik

- C++20 und Qt 6 (dynamisch gelinkt, LGPL), Qt Quick über QRhi auf Direct3D 11. Keine Webtechnik.
- `core/`: reine Logik, mehrkernig. G-Code, Werkzeugweg und Projektdatei sind zeichengenau gegen den aktuellen
  Kotlin-Code geprüft (`tests/golden`, neu erzeugbar nach `tests/golden/README.md`).
- `gpu/`: `SegmentsItem` (Auftragsvorschau, ein Draw-Call je Auftrag, Burn-Map beim Herauszoomen),
  `StageItem` (Editor-Bühne mit Even-Odd per Stencil), `ComputeImage` (Compute-Shader mit CPU-Ersatz).
- `app/`: C++-Backend als QML-Singletons, Oberfläche in `app/qml`, Design-Bausteine in `app/qml/controls`, Farben und Maße nur aus `Theme.qml`.
- `app/src/pi/MachineActions`: einziger Weg zu Maschinenaktionen. Fahr- und Laseraktionen gehen durch den Go-Dialog,
  Enter löst ihn nicht aus, unbekannte Aktionen werden abgelehnt, Service-Funktionen fehlen bewusst.
- `app/src/Automation`: Testtreiber für das echte Fenster, nur mit `LUMACUT_AUTOMATION_PORT` aktiv und nur auf 127.0.0.1.
  Ohne `LUMACUT_PI_URL` schickt die App in diesem Modus nichts ins Netz.

Warum die Fehlerdiffusion nicht auf der GPU läuft: Sie ist seriell und muss im G-Code zeichengenau wie Android bleiben.
Sie läuft mehrkernig je Bild auf der CPU; die GPU rechnet sofortige Vorschau, Graustufen, Kontrast, Schwellwert und Kanten.

## Bauen und prüfen

```bash
cd software/lumacut-native
tools/build.cmd Release
python tests/ui/run_all.py
```

`tests/ui/run_all.py` startet das echte Fenster gegen je einen frischen Simulator (`tools/sim_pi.py`, braucht flask und pyserial).
Kern-Tests mit `ctest --test-dir build -LE speed`. Die CI (`.github/workflows/lumacut-native.yml`) baut die MSI, installiert sie,
führt alles im installierten Programm aus, deinstalliert und legt eine Vorabversion `windows-<version>` an.

## Messwerte (Stand 06.11.2026, RX 5700 XT, 16 Threads)

| Messung | Wert |
|---|---|
| Erstes Bild ab Prozessstart | 416 bis 430 ms |
| Speicher nach dem Start | 93 bis 126 MB |
| 1 Mio. Segmente, roh, jedes Segment gezeichnet | 3,0 ms je Bild (330 Bilder/s) |
| 5 Mio. Segmente, roh | 12,5 ms je Bild (80 Bilder/s) |
| 20 Mio. Segmente, roh | 47 ms je Bild (21 Bilder/s) |
| Dieselben Aufträge ganz im Bild, Burn-Map | unter 0,6 ms je Bild |
| Software-Adapter WARP, 1 Mio. | 25 bis 29 ms je Bild |
| Vom geänderten Motiv bis zur Vorschau, 1 Mio. | 305 ms |
| Vom geänderten Motiv bis zur Vorschau, 5 Mio. | 953 ms |
| Editor, 100.000 Pfade: alle ziehen | 14,6 ms je Mausbewegung (Median) |
| Foto 2000 × 2000 Dither: G-Code plus Werkzeugweg | etwa 0,3 bis 0,4 s (TypeScript: 4,1 s) |
| Compute 12 MP Graustufen und Kontrast | 0,8 ms GPU, 14,5 ms CPU mit 16 Threads |
| Import SVG 100.000 Pfade | 224 ms, 105 MB (TypeScript: 764 bis 920 ms, 318 bis 343 MB) |
| Import DXF 100.000 Linien | 94 ms, 44 MB (TypeScript: 304 bis 310 ms) |
| MSI | 36 MB |

Die CI hat keine echte GPU; dort läuft die App auf dem Software-Adapter.

## Stand der ersten nativen Etappe

Am 07.11. lief die App mit dem Besitzer vor Ort an der echten Maschine, Ergebnis in [WINDOWS_APP_PI_TEST.md](WINDOWS_APP_PI_TEST.md). Lesender Vorab-Check: `tools/pi_readonly_check.py` führt die App durch alle Ansichten und sperrt jeden Schreibzugriff, am 07.11. bestanden. Ablauf des Tests vor Ort: [WINDOWS_APP_PI_TEST.md](WINDOWS_APP_PI_TEST.md).

**Fertig, im echten Fenster gegen den Simulator geprüft**
- Hülle: Kopfzeile, NOT-AUS auch über Dialogen und mit Taste Pause, Fortschrittsstreifen, Statuszeile, hell und dunkel.
- Maschine: Status, Referenz mit Rückfrage, Jog mit Tastatur, Abtasten, Parken, Licht, Abluft, Sperrstreifen, Kamera, Kalibrierstand, System.
- Material und Optionen. Update-Prüfung gegen lokalen Ersatz-Server.
- Motiv: Formen, Text mit Systemschriften, Stift und Knoten, Ebenen, Boolesche Operationen, Ausrichten, Platten, Bilder, Vektorisieren, Warnungen, Kamera-Hintergrund.
- Starten: Vorschau, Abspielen, Zeitschätzung, Prüfungen, Rahmen, Start mit Go, Lauf, Warteschlange, gespeicherte Aufträge, Abgleich mit dem Pi, Autosave.
- Import: SVG, DXF, HPGL, LightBurn, xTool, Bilder. Export: SVG, DXF, PNG. Kaputte Dateien bringen die App nicht zum Absturz.

**Begonnen oder eingeschränkt**
- Werkstatt und Platine sind Platzhalter mit ehrlichem Hinweis. Beides gibt es fertig in der Tauri-Fassung als Vorlage.
- Kalibrier-Assistenten nur für Bewegung, Bettkarte und Materialtest. Arbeitsplatz-Scan und Platzieren per Kamera fehlen.
- PDF nur Seite 1 als Bild. Die Compute-Vorschau zeigt bei allen Dither-Arten geordnetes Dither, exakt ist erst das Bild auf der Bühne.
- Fortschritt im Lauf ist anteilig über die Zeilen. Der Pi teilt Bahnen auf, deshalb weicht die Anzeige ab.
- Aufträge über 32 MB nimmt der Pi nicht an (Prüfung in der App); die Vorschau schafft mehr.

**Nicht geprüft**
- Echte Maschine, echter Pi, echtes Lasern.
- Echte Dateien aus LightBurn und `.xs` (nur selbst gebaute). Native Dateidialoge und Drag & Drop nur per Code, Schatten und Snap-Flyout mit echter Maus, Hi-DPI.
- Echter Update-Lauf von Version zu Version mit GitHub und msiexec.
- Grafik-Geräteverlust (nur erzwungener Neuaufbau getestet).
- Öffnen und Bauen in der Visual-Studio-Oberfläche (die Voreinstellungen sind da, gebaut wurde per Kommandozeile).

**Nächste Etappen**
1. Am echten Pi mit dem Besitzer vor Ort: lesen, Referenz, Jog, ein kleiner Auftrag auf Testmaterial.
2. Werkstatt nativ. 3. Platine nativ. 4. Arbeitsplatz-Scan, Platzieren, restliche Kalibrierungen.
5. Pi-Einstellungen bearbeiten, Firmware-Update vor Ort. 6. Vektor-PDF. 7. Code-Signing, wenn der Besitzer ein Zertifikat kauft.
