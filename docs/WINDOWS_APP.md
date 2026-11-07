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

Schnell eine MSI zum Ausprobieren, lokal in einem Schritt (inkrementell bauen, Kern-Tests, packen, etwa 1 Minute ohne Codeänderung):

```bash
tools/msi.cmd            # oder: tools/msi.cmd schnell (ohne Tests), tools/msi.cmd fenster (mit Fenster-Tests)
```

Die MSI liegt danach in `software/lumacut-native/dist/LumaCut-Studio-<version>.msi`. Die Version folgt in CI und lokal derselben Regel (`tools/version.ps1`: 0.<Monat seit 12/2025>.<Tag × 1440 + Minute>, UTC), so ersetzt jede neuere MSI die ältere. Die CI läuft nebenher weiter und prüft die installierte MSI auf einem leeren Rechner.

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
- Werkstatt (07.11.): Materialtest-Raster, Box mit Fingerzinken, Zahnrad, Lineal, Maßstab, Rahmen, Seriennummern, Stempel, QR-Code (eigene Umsetzung, Bit für Bit gegen eine Vergleichsbibliothek geprüft), jeweils mit GPU-Vorschau und „Ins Projekt“. Es fehlen Vorlagen (Schild, Untersetzer, Anhänger, Etikett), Schachteln und ein eigener Fotogravur-Assistent (bis dahin Verweis auf die Bildwerkzeuge im Motiv).
- Lochraster (07.11., Platine → Lochraster): Vorlagen 20×80, 30×70, 40×60, 50×70, 70×90 mm (Raster 2,54, Werte mit dem Messschieber prüfen), Bibliothek mit 35 Bauteilen (Widerstand, Diode, LED, Kondensatoren, TO-92, TO-220, DIP-Sockel, Leisten, Klemme, Taster, Poti, Drahtbrücke, Nano, ESP32), Verbindungen als Lötbrücke oder Draht, Beschriftung, Ansicht von oben und gespiegelt von unten, Prüfungen (Kurzschluss, Doppelbelegung, Überlappung, Schrift zu klein, Lack zwischen den Pads), Stückliste, Bestückungs-Assistent, Export CSV/PNG/SVG, eigene Datei `.lumaraster`. „Ins Projekt“ legt Bestückungsseite und gespiegelte Lötseite als Markieren an, Pads werden ausgespart, nie Schneiden. Verbindungswege laufen in der Lackgasse neben den Löchern; Schrift über dem Lochfeld geht großteils verloren. Für Lötstopplack gibt es noch keine Werte, zuerst Materialtest. Nicht geprüft: echte Platine, Maus-Ziehen, Autosave, native Dialoge; Netze fehlen.
- Werkstatt, Platinen (07.11.): Halterung aus MDF 3 mm mit Tasche an der gemeinsamen Lage (`perfboard/x`, `perfboard/y`, Vorgabe 185/197,5), eigene Ebene „Halterung schneiden“, Wendeachse markiert; Materialtest Lötstopplack (8–20 %, Vorschlag, nicht geprüft). Schnitt, Passung und Wenden an der Maschine nicht geprüft.
- Platine (07.11.): Gerber RS-274X (Aperturen, Makros, Regionen, Bögen, Step-and-Repeat, X2) und Excellon, Lagen erkennen, ZIP, Raster, Isolation, Fotofilm, Bohrmarken, Passmarken, Lötstopp, Bestückungsdruck, Spiegeln der Unterseite, Prüfungen, Zeitschätzung, GPU-Vorschau mit Ebenen, „Ins Projekt“ auf eigene Platte, gelasert wird nur über Starten. Beispielplatine 150 × 100 mm mit 1000 Pads: lesen 102 ms, Isolation 438 ms. Nur mit selbst gebauten Dateien geprüft, nicht mit echten KiCad- oder EasyEDA-Exporten; Dateidialog, ZIP und Drag & Drop nicht im Fenster geprüft; Platine liegt immer mittig, Verschieben im Motiv; Schlitze ohne Bohrmarke.
- Kalibrier-Assistenten nur für Bewegung, Bettkarte und Materialtest; der Kamera-Kalibrier-Assistent fehlt nativ (Kalibrierung vom Tablet wird gelesen).
- Kamera (07.11., Motiv → Kamera): Arbeitsplatz-Scan wie Android (ein Go, Kopf zuerst auf die kalibrierte Scanhöhe, ohne gemessene Oberfläche bei falschem Z gesperrt, Bilder entzerrt und überblendet, Speichern auf dem Pi für alle Geräte, fremde Scans werden übernommen), Scan als Hintergrund in Motiv und Starten, Live-Fenster und entzerrtes Live-Bild an der Kopfposition. Nur im Simulator geprüft. In Starten liegt der Scan halbdurchsichtig über dem Auftrag; der Scan tastet nicht selbst ab, sondern verweist auf Abtasten.
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
2. Werkstatt: Vorlagen und Fotogravur-Assistent. 3. Platine: echte Exporte, Lage auf dem Bett. 4. Arbeitsplatz-Scan, Platzieren, restliche Kalibrierungen.
5. Pi-Einstellungen bearbeiten, Firmware-Update vor Ort. 6. Vektor-PDF. 7. Code-Signing, wenn der Besitzer ein Zertifikat kauft.
